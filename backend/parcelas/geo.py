"""
Geographic helpers for parcels: administrative location (CAOP), overlap
detection and terrain (altitude / slope / aspect) from a DEM.
"""
import io
import json
import logging
import math
import urllib.parse
import urllib.request

from django.conf import settings
from django.contrib.gis.db.models.functions import Area, Intersection, Transform
from django.contrib.gis.geos import Point

logger = logging.getLogger(__name__)

PT_TM06 = 3763
MIN_OVERLAP_HA = 0.05     # ignore slivers from slightly misaligned drawings
MIN_OVERLAP_FRACTION = 0.01


def area_ha(geom):
    return round(geom.transform(PT_TM06, clone=True).area / 10000, 4)


# ── Administrative location (CAOP) ───────────────────────────────────────────

def admin_location(geom):
    """
    Concelho / freguesia(s) / distrito of a WGS84 polygon from the CAOP table.
    The main concelho is the one with the largest share of the parcel; all
    intersected freguesias are listed (largest first).
    Returns None when the CAOP has not been loaded or nothing intersects.
    """
    from .models import Freguesia
    g = geom.transform(PT_TM06, clone=True)
    hits = list(Freguesia.objects.filter(geom__intersects=g)
                .annotate(part=Area(Intersection('geom', g)))
                .order_by('-part')
                .values('freguesia', 'concelho', 'distrito'))
    if not hits:
        return None
    main = hits[0]
    return {
        'concelho':  main['concelho'],
        'distrito':  main['distrito'],
        'freguesia': '; '.join(h['freguesia'] for h in hits)[:300],
        'concelhos': list(dict.fromkeys(h['concelho'] for h in hits)),
    }


def apply_location(parcel):
    """Fill concelho/freguesia/distrito from the CAOP (leaves them untouched if unavailable)."""
    loc = admin_location(parcel.geometry)
    if loc:
        parcel.concelho, parcel.freguesia, parcel.distrito = loc['concelho'], loc['freguesia'], loc['distrito']
    return loc


# ── Overlaps ─────────────────────────────────────────────────────────────────

def overlapping_parcels(geom, exclude_pk=None):
    """Existing parcels whose overlap with `geom` is more than a sliver: [(parcel, overlap_ha)]."""
    from .models import FireParcel
    g = geom.transform(PT_TM06, clone=True)
    own_ha = g.area / 10000
    qs = FireParcel.objects.filter(geometry__intersects=geom)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    qs = qs.annotate(overlap=Area(Intersection(Transform('geometry', PT_TM06), g)))
    result = []
    for p in qs:
        ha = p.overlap.sq_m / 10000
        if ha >= MIN_OVERLAP_HA or (own_ha and ha / own_ha >= MIN_OVERLAP_FRACTION):
            result.append((p, round(ha, 2)))
    return sorted(result, key=lambda x: -x[1])


# ── Terrain ──────────────────────────────────────────────────────────────────

TERRAIN_ZOOM = 13          # MapTiler terrain-RGB v2 (512 px tiles): ~7.6 m/pixel at 37°N
SLOPE_SCALE_M = 25         # slope over ~25 m (like EU-DEM): general slope, not micro-relief
MAX_TILES = 9              # a z13 tile is ~3.9 km wide here; larger parcels fall back to Open-Meteo
ASPECT_NAMES = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
FLAT_SLOPE_PCT = 2.0


def _tile_xy(lat, lng, z):
    n = 2 ** z
    x = (lng + 180) / 360 * n
    lat_r = math.radians(lat)
    y = (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n
    return x, y


def _pixel_lnglat(px, py, z, tile_px):
    n = 2 ** z * tile_px
    lng = px / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * py / n))))
    return lng, lat


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={'User-Agent': 'FogoBomAlgarve/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _aspect_name(deg):
    return ASPECT_NAMES[int(((deg % 360) + 22.5) // 45) % 8]


def terrain_maptiler(geom):
    """Mean altitude, mean slope (%) and dominant aspect over the polygon, from MapTiler terrain-RGB."""
    from PIL import Image
    key = settings.MAPTILER_API_KEY
    if not key:
        raise RuntimeError('MAPTILER_API_KEY não configurada')
    z = TERRAIN_ZOOM
    xmin, ymin, xmax, ymax = geom.extent  # lng/lat
    gx0, gy0 = _tile_xy(ymax, xmin, z)    # fractional tile coordinates of the bbox corners
    gx1, gy1 = _tile_xy(ymin, xmax, z)
    tx0, ty0, tx1, ty1 = int(gx0), int(gy0), int(gx1), int(gy1)
    tiles = [(tx, ty) for tx in range(tx0, tx1 + 1) for ty in range(ty0, ty1 + 1)]
    if len(tiles) > MAX_TILES:
        raise RuntimeError('parcela demasiado grande para o cálculo automático do relevo')

    images = {}
    for tx, ty in tiles:
        url = f'https://api.maptiler.com/tiles/terrain-rgb-v2/{z}/{tx}/{ty}.png?key={urllib.parse.quote(key)}'
        images[(tx, ty)] = Image.open(io.BytesIO(_fetch(url))).convert('RGB')
    # terrain-rgb-v2 serves 512 px tiles; read the size instead of assuming it
    tp = next(iter(images.values())).size[0]

    # Mosaic elevations into one grid
    w, h = (tx1 - tx0 + 1) * tp, (ty1 - ty0 + 1) * tp
    elev = [[None] * w for _ in range(h)]
    for (tx, ty), img in images.items():
        data = list(img.getdata())
        ox, oy = (tx - tx0) * tp, (ty - ty0) * tp
        for j in range(tp):
            row = elev[oy + j]
            for i in range(tp):
                r, g, b = data[j * tp + i]
                row[ox + i] = -10000 + (r * 65536 + g * 256 + b) * 0.1

    lat_c = (ymin + ymax) / 2
    cell = math.cos(math.radians(lat_c)) * 2 * math.pi * 6378137 / (tp * 2 ** z)
    # Horn kernel spaced k pixels apart so the slope is measured over ~SLOPE_SCALE_M
    k = max(1, round(SLOPE_SCALE_M / cell))
    # Only visit pixels inside the parcel's bounding box
    i0, i1 = max(int(gx0 * tp) - tx0 * tp, k), min(int(gx1 * tp) - tx0 * tp + 1, w - 1 - k)
    j0, j1 = max(int(gy0 * tp) - ty0 * tp, k), min(int(gy1 * tp) - ty0 * tp + 1, h - 1 - k)
    inside = geom.prepared
    e = elev
    alts, slopes, sx, sy = [], [], 0.0, 0.0
    for j in range(j0, j1 + 1):
        for i in range(i0, i1 + 1):
            lng, lat = _pixel_lnglat(tx0 * tp + i + 0.5, ty0 * tp + j + 0.5, z, tp)
            if not inside.contains(Point(lng, lat, srid=4326)):
                continue
            dzdx = ((e[j-k][i+k] + 2*e[j][i+k] + e[j+k][i+k]) - (e[j-k][i-k] + 2*e[j][i-k] + e[j+k][i-k])) / (8 * k * cell)
            dzdy = ((e[j-k][i-k] + 2*e[j-k][i] + e[j-k][i+k]) - (e[j+k][i-k] + 2*e[j+k][i] + e[j+k][i+k])) / (8 * k * cell)
            alts.append(e[j][i])
            slopes.append(math.hypot(dzdx, dzdy) * 100)
            # downslope direction (east, north components)
            sx += -dzdx
            sy += -dzdy
    if not alts:   # very small parcel: use the pixel at the centroid
        c = geom.centroid
        x, y = _tile_xy(c.y, c.x, z)
        i, j = int(x * tp) - tx0 * tp, int(y * tp) - ty0 * tp
        i, j = min(max(i, k), w - 1 - k), min(max(j, k), h - 1 - k)
        alts, slopes = [elev[j][i]], [0.0]
    return _summary(alts, slopes, sx, sy, f'MapTiler (~{cell:.0f} m)')


def terrain_open_meteo(geom):
    """Fallback: Open-Meteo elevation (~90 m) on a sample grid + least-squares plane."""
    g = geom.transform(PT_TM06, clone=True)
    xmin, ymin, xmax, ymax = g.extent
    step = max(math.sqrt((xmax - xmin) * (ymax - ymin) / 80), 30)
    pts = []
    y = ymin + step / 2
    while y < ymax:
        x = xmin + step / 2
        while x < xmax:
            p = Point(x, y, srid=PT_TM06)
            if g.contains(p):
                pts.append(p)
            x += step
        y += step
    pts = (pts or [g.centroid])[:100]
    wgs = [p.transform(4326, clone=True) for p in pts]
    q = urllib.parse.urlencode({'latitude': ','.join(f'{p.y:.6f}' for p in wgs),
                                'longitude': ','.join(f'{p.x:.6f}' for p in wgs)})
    z = json.loads(_fetch(f'https://api.open-meteo.com/v1/elevation?{q}'))['elevation']
    alts = [float(v) for v in z]
    if len(pts) < 3:
        return _summary(alts, [0.0], 0, 0, 'Open-Meteo (~90 m)')
    # Fit z = a*x + b*y + c (normal equations, 3x3)
    xs, ys = [p.x for p in pts], [p.y for p in pts]
    n = len(xs)
    sxx = sum(v * v for v in xs); syy = sum(v * v for v in ys); sxy = sum(a * b for a, b in zip(xs, ys))
    sx_ = sum(xs); sy_ = sum(ys); sz = sum(alts)
    sxz = sum(a * b for a, b in zip(xs, alts)); syz = sum(a * b for a, b in zip(ys, alts))
    m = [[sxx, sxy, sx_], [sxy, syy, sy_], [sx_, sy_, n]]
    v = [sxz, syz, sz]
    a, b, _ = _solve3(m, v)
    return _summary(alts, [math.hypot(a, b) * 100], -a, -b, 'Open-Meteo (~90 m)')


def _solve3(m, v):
    """Cramer's rule for a 3x3 system."""
    def det(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
                - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    d = det(m)
    if abs(d) < 1e-9:
        return 0.0, 0.0, 0.0
    out = []
    for k in range(3):
        mk = [row[:] for row in m]
        for r in range(3):
            mk[r][k] = v[r]
        out.append(det(mk) / d)
    return out


def _summary(alts, slopes, east, north, source):
    slope = sum(slopes) / len(slopes)
    if slope < FLAT_SLOPE_PCT or (east == 0 and north == 0):
        aspect = 'plano'
    else:
        aspect = _aspect_name(math.degrees(math.atan2(east, north)))
    return {'altitude_m': round(sum(alts) / len(alts)), 'slope_pct': round(slope, 1),
            'aspect': aspect, 'source': source}


def terrain(geom):
    """Best-effort terrain summary; returns None if every source fails."""
    for fn in (terrain_maptiler, terrain_open_meteo):
        try:
            return fn(geom)
        except Exception as exc:
            logger.warning('Relevo (%s) falhou: %s', fn.__name__, exc)
    return None
