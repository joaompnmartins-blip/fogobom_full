"""
Cost estimate per PFC parcel from the CAOF matrix (jornas/ha) plus the costs it
excludes (plan elaboration, containment strips), compared with ICNF support.
Values come from CostSettings (admin-editable); intermediate matrix cells are an
explicit additive rule reproducing the published extremes (1 → 4/5 jornas/ha).
"""
from decimal import Decimal

from .models import CostSettings

PT_TM06 = 3763


def slope_class(slope_pct):
    if slope_pct is None:
        return '0-10'
    return '0-10' if slope_pct <= 10 else '10-25' if slope_pct <= 25 else '>25'


def default_inputs(parcel):
    """CAOF inputs suggested from the parcel and its latest completed evaluation."""
    ev = parcel.evaluations.filter(completed_at__isnull=False).order_by('-completed_at').first()
    return {
        'cost_type': 'mato' if parcel.vegetation_type == 'matos' else 'povoamento',
        'cost_slope': slope_class(ev.slope_pct if ev else None),
        'cost_load': 'alta' if ev and ev.fuel_load == 'alta' else 'baixa',
    }


def area_class(area_ha, cost_type, cfg):
    large = cfg.large_area_mato_ha if cost_type == 'mato' else cfg.large_area_povoamento_ha
    if area_ha < cfg.small_area_ha:
        return 'pequena', f'< {cfg.small_area_ha:g} ha'
    if area_ha > large:
        return 'grande', f'> {large:g} ha'
    return 'intermedia', f'{cfg.small_area_ha:g}–{large:g} ha'


def jornas_per_ha(pp, cfg):
    area = pp.parcel.area_ha or 0
    j = cfg.base_jornas
    j += {'0-10': 0, '10-25': cfg.slope_mid_jornas, '>25': cfg.slope_high_jornas}[pp.cost_slope]
    j += {'grande': 0, 'intermedia': cfg.area_mid_jornas, 'pequena': cfg.area_small_jornas}[
        area_class(area, pp.cost_type, cfg)[0]]
    if pp.cost_type == 'povoamento' and pp.cost_load == 'alta':
        j += cfg.load_high_jornas
    cap = cfg.max_jornas_mato if pp.cost_type == 'mato' else cfg.max_jornas_povoamento
    return min(j, cap)


def _d(value):
    return Decimal(str(value))


def parcel_estimate(pp, cfg=None):
    cfg = cfg or CostSettings.current()
    area = _d(pp.parcel.area_ha or 0)
    j = jornas_per_ha(pp, cfg)
    jorna = _d(cfg.jorna_eur)
    burn = _d(j) * jorna * area
    perimeter_m = pp.parcel.geometry.transform(PT_TM06, clone=True).length if pp.parcel.geometry else 0
    strip = _d(perimeter_m * cfg.strip_fraction) * _d(cfg.strip_eur_per_m)
    rate = _d(cfg.support_mato_eur_ha if pp.cost_type == 'mato' else cfg.support_povoamento_eur_ha)
    support = rate * area
    total = burn + strip
    return {
        'pp': pp,
        'area_ha': float(area),
        'area_class': area_class(float(area), pp.cost_type, cfg)[1],
        'jornas_ha': j,
        'eur_ha': (_d(j) * jorna).quantize(Decimal('0.01')),
        'burn': burn.quantize(Decimal('0.01')),
        'perimeter_m': round(perimeter_m),
        'strip': strip.quantize(Decimal('0.01')),
        'total': total.quantize(Decimal('0.01')),
        'support': support.quantize(Decimal('0.01')),
        'coverage_pct': round(float(support / total * 100)) if total else None,
    }


def pfc_estimate(pfc):
    cfg = CostSettings.current()
    rows = [parcel_estimate(pp, cfg) for pp in pfc.plan_parcels.select_related('parcel')]
    plan = (_d(cfg.plan_jornas) * _d(cfg.jorna_eur)).quantize(Decimal('0.01'))
    burn = sum((r['burn'] for r in rows), Decimal('0'))
    strip = sum((r['strip'] for r in rows), Decimal('0'))
    support = sum((r['support'] for r in rows), Decimal('0'))
    total = burn + strip + plan
    area = sum(r['area_ha'] for r in rows)
    return {
        'rows': rows, 'cfg': cfg, 'plan': plan, 'burn': burn, 'strip': strip, 'support': support,
        'total': total, 'area_ha': round(area, 2),
        'eur_ha': (total / Decimal(str(area))).quantize(Decimal('0.01')) if area else None,
        'coverage_pct': round(float(support / total * 100)) if total else None,
    }
