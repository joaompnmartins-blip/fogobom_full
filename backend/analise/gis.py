"""Vector exports of parcels and treated areas: GeoJSON and KML in WGS84, Shapefile (zip) and GeoPackage in
PT-TM06/ETRS89 (EPSG:3763), the system ICNF uses. Shapefile/GeoPackage/KML are produced with GDAL's ogr2ogr.

Contact data of the parcels (name / email) is never exported."""
import io
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from fire_actions.models import ParcelExecution
from parcelas.models import FireParcel

FORMATS = {
    'geojson': ('application/geo+json', None),
    'kml': ('application/vnd.google-earth.kml+xml', 'KML'),
    'shp': ('application/zip', 'ESRI Shapefile'),
    'gpkg': ('application/geopackage+sqlite3', 'GPKG'),
}
FORMAT_LABELS = [('geojson', 'GeoJSON'), ('kml', 'KML (Google Earth)'), ('shp', 'Shapefile (PT-TM06)'),
                 ('gpkg', 'GeoPackage (PT-TM06)')]
PT_TM06 = 'EPSG:3763'


class ExportError(Exception):
    pass


def ogr2ogr_available():
    return shutil.which('ogr2ogr') is not None


def _d(d):
    return d.isoformat() if d else None


def parcel_features(parcels):
    """Parcels with their status and burn history. Attribute names fit the 10-character Shapefile limit."""
    last = {}
    count = {}
    for pid, d in ParcelExecution.objects.filter(parcel__in=parcels).values_list('parcel_id', 'date'):
        count[pid] = count.get(pid, 0) + 1
        last[pid] = max(last.get(pid, d), d)
    out = []
    for p in parcels:
        if not p.geometry:
            continue
        out.append({'geometry': p.geometry, 'properties': {
            'id': p.pk, 'nome': p.name, 'estado': p.get_status_display(), 'tipologia': p.get_vegetation_type_display(),
            'area_ha': round(p.area_ha, 4) if p.area_ha is not None else None,
            'distrito': p.distrito, 'concelho': p.concelho, 'freguesia': p.freguesia,
            'infraestr': p.get_infrastructure_display(), 'ult_queima': _d(last.get(p.pk)),
            'n_queimas': count.get(p.pk, 0),
        }})
    return out


def execution_features(executions, numbers=None):
    """One feature per parcel execution (POQ-Execução: "cartografia das parcelas tratadas")."""
    out = []
    for ex in executions:
        action = ex.plan.pre_plan
        pfc_numbers = numbers if numbers is not None else (
            dict(action.pfc.plan_parcels.values_list('parcel_id', 'number')) if action.pfc_id else {})
        if not ex.parcel.geometry:
            continue
        out.append({'geometry': ex.parcel.geometry, 'properties': {
            'id_parc': str(pfc_numbers.get(ex.parcel_id, ex.parcel.name)), 'parcela': ex.parcel.name,
            'data': _d(ex.date), 'inicio': ex.start_time.strftime('%H:%M') if ex.start_time else None,
            'fim': ex.end_time.strftime('%H:%M') if ex.end_time else None,
            'area_trat': ex.area_treated_ha, 'formacao': ex.get_formation_display(),
            'acao': action.name, 'tipo': action.get_action_type_display(), 'formacao_a': 'Sim' if action.training
            else 'Não', 'pfc': action.pfc.number if action.pfc_id else (action.pfc_reference or None),
            'concelho': ex.parcel.concelho, 'freguesia': ex.parcel.freguesia,
            'eficacia': ex.get_rating_objectives_display() or None, 'fuga': 'Sim' if ex.plan.incident else 'Não',
        }})
    return out


def to_geojson(features, name):
    return {
        'type': 'FeatureCollection', 'name': name,
        'crs': {'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:OGC:1.3:CRS84'}},
        'features': [{'type': 'Feature', 'geometry': json.loads(f['geometry'].json), 'properties': f['properties']}
                     for f in features],
    }


def export(features, name, fmt):
    """(bytes, content_type, filename) for `fmt` in FORMATS."""
    if fmt not in FORMATS:
        raise ExportError('Formato desconhecido.')
    content_type, driver = FORMATS[fmt]
    data = json.dumps(to_geojson(features, name), ensure_ascii=False).encode()
    if driver is None:
        return data, content_type, f'{name}.geojson'
    if not ogr2ogr_available():
        raise ExportError('A conversão para este formato não está disponível no servidor.')
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'in.geojson'
        src.write_bytes(data)
        if fmt == 'shp':
            dst = Path(tmp) / 'shp' / f'{name}.shp'
            dst.parent.mkdir()
            extra = ['-t_srs', PT_TM06, '-lco', 'ENCODING=UTF-8']
        elif fmt == 'gpkg':
            dst = Path(tmp) / f'{name}.gpkg'
            extra = ['-t_srs', PT_TM06, '-nln', name]
        else:
            dst = Path(tmp) / f'{name}.kml'
            name_field = 'nome' if features and 'nome' in features[0]['properties'] else 'parcela'
            extra = ['-dsco', f'NameField={name_field}']
        cmd = ['ogr2ogr', '-f', driver, str(dst), str(src), *extra]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            err = getattr(exc, 'stderr', b'') or b''
            raise ExportError(f'Erro na conversão: {err.decode(errors="replace")[:300]}') from exc
        if fmt == 'shp':
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
                for f in sorted(dst.parent.iterdir()):
                    z.write(f, f.name)
            return buf.getvalue(), content_type, f'{name}_PT-TM06.zip'
        suffix = '_PT-TM06.gpkg' if fmt == 'gpkg' else '.kml'
        return dst.read_bytes(), content_type, f'{name}{suffix}'


def filtered_parcels(params):
    qs = FireParcel.objects.all()
    for key, field in (('estado', 'status'), ('concelho', 'concelho'), ('tipologia', 'vegetation_type')):
        if params.get(key):
            qs = qs.filter(**{field: params[key]})
    return list(qs.order_by('name'))
