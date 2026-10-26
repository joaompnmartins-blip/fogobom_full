"""
Outlook for an announced action: rural fire danger (IPMA), fine dead fuel
moisture forecast (same method as the weather page: Simard EMC 08–18 h with
the slope/aspect correction table and the antecedent-rain rule) and legal
framework → suggested probability with the reasons.
"""
import json
import logging
import math
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

IPMA_URL = 'https://api.ipma.pt/open-data/forecast/meteorology/rcm/rcm-d{d}.json'
IPMA_LEVELS = {1: 'Reduzido', 2: 'Moderado', 3: 'Elevado', 4: 'Muito elevado', 5: 'Máximo'}
IPMA_BLOCKING = 4           # «muito elevado» or «máximo»: burning not allowed (DL 82/2021, art. 63.º/65.º)
FORECAST_DAYS = 16          # Open-Meteo horizon
RAIN_THRESHOLD = 1.0        # mm/day
CACHE_SECONDS = 3 * 3600


def _get_json(url, timeout=15):
    from django.conf import settings
    if getattr(settings, 'EXTERNAL_HTTP_DISABLED', False):
        raise RuntimeError('pedidos externos desligados (testes)')
    req = urllib.request.Request(url, headers={'User-Agent': 'FogoBomAlgarve/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ── IPMA rural fire danger ───────────────────────────────────────────────────

def ipma_day(d):
    """{dico: level} for date `d` (only today .. today+2 are published), cached."""
    offset = (d - timezone.localdate()).days
    if offset < 0 or offset > 2:
        return None
    key = f'ipma-rcm-{d.isoformat()}'
    data = cache.get(key)
    if data is None:
        try:
            raw = _get_json(IPMA_URL.format(d=offset))
            if raw.get('dataPrev') != d.isoformat():
                return None
            data = {k: v['data']['rcm'] for k, v in raw.get('local', {}).items()}
        except Exception as exc:
            logger.warning('IPMA indisponível: %s', exc)
            return None
        cache.set(key, data, CACHE_SECONDS)
    return data


def concelho_dicos(concelhos):
    from parcelas.models import Freguesia
    codes = Freguesia.objects.filter(concelho__in=concelhos).values_list('concelho', 'dicofre')
    return {c: code[:4] for c, code in codes}


def fire_danger(concelhos, d):
    """Highest IPMA level among the concelhos on date `d`: (level, label, per_concelho) or None."""
    levels = ipma_day(d)
    if levels is None or not concelhos:
        return None
    per = {c: levels.get(dico) for c, dico in concelho_dicos(concelhos).items() if levels.get(dico)}
    if not per:
        return None
    top = max(per.values())
    return {'level': top, 'label': IPMA_LEVELS.get(top, str(top)), 'per_concelho': per,
            'blocking': top >= IPMA_BLOCKING}


# ── Fuel moisture (port of core/static/core/firedpt.js) ──────────────────────

def simard_emc(temp_c, rh):
    """Simard (1968) EMC for fine dead fuels; RH in %, T converted to °F."""
    t = temp_c * 9 / 5 + 32
    if rh <= 10:
        emc = 0.03229 + 0.281073 * rh - 0.000578 * t
    elif rh < 50:
        emc = 2.22749 + 0.160107 * rh - 0.014784 * t
    else:
        emc = 21.0606 + 0.005565 * rh * rh - 0.0003505 * rh * t - 0.483199 * rh
    return max(1.0, min(40.0, emc))


CORRECTION = {  # [season][aspect][slope class][hour band 8-10,10-12,12-14,14-16,16-18]
    'FEB_OCT': {'N': {'0-30': [4, 2, 1, 1, 4], '>30': [4, 3, 3, 3, 4]},
                'E': {'0-30': [4, 2, 1, 1, 4], '>30': [3, 1, 1, 2, 5]},
                'S': {'0-30': [4, 2, 1, 1, 4], '>30': [4, 2, 1, 1, 4]},
                'W': {'0-30': [4, 2, 1, 1, 4], '>30': [5, 4, 2, 1, 3]}},
    'MAY_JUL': {'N': {'0-30': [3, 1, 0, 1, 3], '>30': [4, 2, 1, 2, 4]},
                'E': {'0-30': [2, 1, 0, 1, 4], '>30': [2, 0, 0, 3, 5]},
                'S': {'0-30': [3, 1, 0, 1, 3], '>30': [3, 1, 1, 1, 3]},
                'W': {'0-30': [3, 1, 0, 1, 3], '>30': [5, 3, 1, 0, 2]}},
    'NOV_JAN': {'N': {'0-30': [5, 4, 3, 3, 4], '>30': [5, 5, 5, 5, 5]},
                'E': {'0-30': [5, 4, 3, 5, 4], '>30': [5, 4, 3, 2, 5]},
                'S': {'0-30': [5, 4, 3, 2, 4], '>30': [5, 3, 1, 1, 3]},
                'W': {'0-30': [5, 4, 3, 3, 4], '>30': [5, 5, 4, 2, 3]}},
}
ASPECT_DEG = {'N': 0, 'NE': 45, 'E': 90, 'SE': 135, 'S': 180, 'SW': 225, 'W': 270, 'NW': 315}


def correction(month, aspect_deg, slope_pct, hour):
    if hour < 8 or hour > 18:
        return 0
    band = min((hour - 8) // 2, 4)
    season = ('FEB_OCT' if month in (2, 3, 4, 8, 9, 10) else 'MAY_JUL' if month in (5, 6, 7) else 'NOV_JAN')
    cardinal = 'N' if aspect_deg >= 315 or aspect_deg < 45 else 'E' if aspect_deg < 135 \
        else 'S' if aspect_deg < 225 else 'W'
    slope_class = '0-30' if slope_pct <= 30 else '>30'
    return CORRECTION[season][cardinal][slope_class][band]


def classify(fm):
    if fm > 25:
        return 'Muito húmido', 'NAO-GO'
    if fm > 20:
        return 'Húmido', 'CUIDADO'
    if fm > 15:
        return 'Ótimo', 'GO'
    if fm > 10:
        return 'Seco', 'CUIDADO'
    return 'Muito seco', 'NAO-GO'


def fuel_forecast(lat, lng, d, terrain=None):
    """Daytime fuel moisture for date `d` at a point, or None outside the forecast horizon."""
    today = timezone.localdate()
    if d < today or d > today + timedelta(days=FORECAST_DAYS - 1):
        return None
    key = f'fuel-{lat:.3f}-{lng:.3f}-{today.isoformat()}'
    data = cache.get(key)
    if data is None:
        q = urllib.parse.urlencode({
            'latitude': f'{lat:.4f}', 'longitude': f'{lng:.4f}',
            'hourly': 'temperature_2m,relative_humidity_2m,windspeed_10m,precipitation',
            'daily': 'precipitation_sum', 'timezone': 'auto', 'past_days': 10, 'forecast_days': FORECAST_DAYS})
        try:
            data = _get_json(f'https://api.open-meteo.com/v1/forecast?{q}')
        except Exception as exc:
            logger.warning('Open-Meteo indisponível: %s', exc)
            return None
        cache.set(key, data, CACHE_SECONDS)

    ds = d.isoformat()
    hourly, daily = data['hourly'], data.get('daily', {})
    rain_by_day = dict(zip(daily.get('time', []), daily.get('precipitation_sum', [])))
    days = sorted(rain_by_day)
    dry_days = 0
    if ds in days:
        for prev in reversed(days[:days.index(ds)]):
            if (rain_by_day[prev] or 0) >= RAIN_THRESHOLD:
                break
            dry_days += 1
    slope = terrain.get('slope_pct') if terrain else None
    aspect = ASPECT_DEG.get(terrain.get('aspect')) if terrain else None
    fms, temps, rhs, winds = [], [], [], []
    for i, t in enumerate(hourly['time']):
        if not t.startswith(ds):
            continue
        hour = int(t[11:13])
        if hour < 8 or hour > 18:
            continue
        emc = simard_emc(hourly['temperature_2m'][i], hourly['relative_humidity_2m'][i])
        corr = correction(d.month, aspect, slope, hour) if slope is not None and aspect is not None else 0
        fms.append(max(1.0, emc + corr))
        temps.append(hourly['temperature_2m'][i])
        rhs.append(hourly['relative_humidity_2m'][i])
        winds.append(hourly['windspeed_10m'][i])
    if not fms:
        return None
    fm_mean = sum(fms) / len(fms)
    label, go = classify(fm_mean)
    note = ''
    if dry_days < 1:
        go, note = 'NAO-GO', 'chuva recente — combustível húmido'
    elif dry_days <= 3 and go == 'GO':
        go, note = 'CUIDADO', f'{dry_days} dia(s) sem chuva — humidade residual possível'
    return {'fm_mean': round(fm_mean, 1), 'fm_min': round(min(fms), 1), 'label': label, 'go': go, 'note': note,
            'dry_days': dry_days, 'rain': rain_by_day.get(ds), 't_max': max(temps), 'rh_min': min(rhs),
            'wind_max': max(winds)}


# ── Outlook ──────────────────────────────────────────────────────────────────

PROB_LABELS = {'alta': 'Alta', 'media': 'Média', 'baixa': 'Baixa'}
GO_TO_PROB = {'GO': 'alta', 'CUIDADO': 'media', 'NAO-GO': 'baixa'}
RANK = {'baixa': 0, 'media': 1, 'alta': 2}


def action_outlook(action, d=None):
    """Suggested probability for `action` on date `d` (default: scheduled date) and the reasons."""
    d = d or action.scheduled_date
    parcels = list(action.parcels.all())
    concelhos = sorted({p.concelho for p in parcels if p.concelho})
    reasons, suggestion = [], None

    danger = fire_danger(concelhos, d)
    fuel = None
    if parcels:
        from django.contrib.gis.db.models.functions import Centroid
        p = parcels[0]
        c = type(p).objects.filter(pk=p.pk).annotate(c=Centroid('geometry')).values_list('c', flat=True)[0]
        ev = p.evaluations.filter(completed_at__isnull=False).order_by('-completed_at').first()
        terrain = {'slope_pct': ev.slope_pct, 'aspect': ev.aspect} if ev and ev.slope_pct is not None else None
        fuel = fuel_forecast(c.y, c.x, d, terrain)

    if fuel:
        suggestion = GO_TO_PROB[fuel['go']]
        reasons.append(f"Humidade do combustível prevista {fuel['fm_mean']}% ({fuel['label']})"
                       + (f" — {fuel['note']}" if fuel['note'] else ''))
    if danger:
        reasons.append(f"Perigo de incêndio rural (IPMA): {danger['label']}")
        if danger['blocking']:
            suggestion = 'baixa'
            reasons.append('Com perigo «muito elevado» ou «máximo» a queima não é permitida.')
    missing = action.legal_missing
    if missing:
        reasons.append('Enquadramento legal em falta: ' + '; '.join(missing))
        if suggestion == 'alta':
            suggestion = 'media'
    if not fuel and not danger:
        reasons.append('Ainda sem previsão para esta data (disponível a 16 dias; perigo IPMA a 3 dias).')

    return {
        'date': d,
        'suggested': suggestion,
        'suggested_label': PROB_LABELS.get(suggestion, 'Sem previsão'),
        'probability': action.probability_manual or suggestion,
        'probability_label': PROB_LABELS.get(action.probability_manual or suggestion, 'Sem previsão'),
        'manual': bool(action.probability_manual),
        'fuel': fuel,
        'danger': danger,
        'blocked': bool(danger and danger['blocking']),
        'reasons': reasons,
    }
