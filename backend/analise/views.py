import csv
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from fire_actions.models import BurningPlan, ParcelExecution
from parcelas.models import FireParcel
from pfc.models import PFC
from . import gis
from .stats import compute, years_available

logger = logging.getLogger(__name__)


def _year(request):
    try:
        return int(request.GET.get('ano', ''))
    except ValueError:
        return None


@login_required
def stats_page(request):
    year = _year(request)
    return render(request, 'analise/stats.html', {'s': compute(year), 'year': year, 'years': years_available()})


@login_required
def executions_csv(request):
    """One row per parcel execution, for analysis in a spreadsheet."""
    year = _year(request)
    qs = ParcelExecution.objects.select_related('parcel', 'plan__pre_plan__pfc').prefetch_related(
        'members', 'cost_lines', 'readings').order_by('date', 'parcel__name')
    if year:
        qs = qs.filter(date__year=year)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="execucoes{"_" + str(year) if year else ""}.csv"'
    response.write('﻿')   # Excel opens UTF-8 correctly with a BOM
    w = csv.writer(response, delimiter=';')
    w.writerow(['data', 'acao', 'tipo', 'formacao_acao', 'pfc', 'parcela', 'concelho', 'freguesia', 'formacao',
                'area_tratada_ha', 'inicio', 'fim', 'duracao_h', 'n_pessoas', 'horas_pessoa', 'n_operacionais', 'vfci',
                'vlci', 'leituras_meteo', 'temp_min', 'temp_max', 'hr_min', 'hr_max', 'vento_max_kmh',
                'problemas', 'eficacia_objetivos', 'eficacia_combustivel', 'fuga_do_fogo', 'custo_real_eur'])

    def num(v):
        return '' if v is None else str(round(v, 2)).replace('.', ',')

    for ex in qs:
        a = ex.plan.pre_plan
        rs = list(ex.readings.all())
        temps = [r.temp for r in rs if r.temp is not None]
        rhs = [r.rh for r in rs if r.rh is not None]
        winds = [r.wind_kmh for r in rs if r.wind_kmh is not None]
        members = list(ex.members.all())
        w.writerow([
            ex.date.isoformat(), a.name, a.get_action_type_display(), 'sim' if a.training else 'não',
            a.pfc.number if a.pfc_id else a.pfc_reference, ex.parcel.name, ex.parcel.concelho, ex.parcel.freguesia,
            ex.get_formation_display(), num(ex.area_treated_ha),
            ex.start_time.strftime('%H:%M') if ex.start_time else '', ex.end_time.strftime('%H:%M') if ex.end_time
            else '', num(ex.duration_hours), len(members),
            num(sum((m.hours if m.hours is not None else ex.duration_hours) or 0 for m in members)),
            ex.n_men or '', ex.n_vfci or '', ex.n_vlci or '', len(rs),
            num(min(temps)) if temps else '', num(max(temps)) if temps else '',
            num(min(rhs)) if rhs else '', num(max(rhs)) if rhs else '', num(max(winds)) if winds else '',
            ex.problems_display, ex.get_rating_objectives_display(), ex.get_rating_fuel_display(),
            'sim' if ex.plan.incident else 'não', num(float(ex.cost_total)),
        ])
    return response


@login_required
def gis_page(request):
    parcels = FireParcel.objects.all()
    return render(request, 'analise/gis.html', {
        'formats': gis.FORMAT_LABELS, 'ogr': gis.ogr2ogr_available(),
        'statuses': FireParcel.STATUS_CHOICES,
        'tipologias': FireParcel._meta.get_field('vegetation_type').choices,
        'concelhos': sorted({c for c in parcels.values_list('concelho', flat=True) if c}),
        'years': sorted({d.year for d in ParcelExecution.objects.values_list('date', flat=True)}, reverse=True),
        'plans': BurningPlan.objects.select_related('pre_plan').order_by('-execution_date')[:50],
        'pfcs': PFC.objects.order_by('-validity_start'),
    })


def _send(request, features, name, fmt, back):
    if not features:
        messages.error(request, 'Não há geometrias para exportar com estes critérios.')
        return redirect(back)
    try:
        content, content_type, filename = gis.export(features, name, fmt)
    except gis.ExportError as exc:
        logger.warning('Exportação GIS falhou: %s', exc)
        messages.error(request, str(exc))
        return redirect(back)
    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def gis_parcels(request, fmt):
    parcels = gis.filtered_parcels(request.GET)
    return _send(request, gis.parcel_features(parcels), 'parcelas', fmt, 'analise:gis')


@login_required
def gis_executions(request, fmt):
    year = _year(request)
    qs = ParcelExecution.objects.select_related('parcel', 'plan__pre_plan__pfc').order_by('date')
    if year:
        qs = qs.filter(date__year=year)
    name = f'areas_tratadas_{year}' if year else 'areas_tratadas'
    return _send(request, gis.execution_features(qs), name, fmt, 'analise:gis')


@login_required
def gis_plan(request, plan_pk, fmt):
    """Treated parcels of one POQ-Execução (cartografia vetorial a enviar ao ICNF)."""
    plan = get_object_or_404(BurningPlan.objects.select_related('pre_plan__pfc'), pk=plan_pk)
    qs = plan.executions.select_related('parcel', 'plan__pre_plan__pfc').order_by('date', 'parcel__name')
    ref = plan.pre_plan.pfc.number.replace('/', '-') if plan.pre_plan.pfc_id else plan.pre_plan.name[:40]
    return _send(request, gis.execution_features(qs), f'POQ_{ref}_{plan.execution_date:%Y%m%d}'.replace(' ', '_'),
                 fmt, request.META.get('HTTP_REFERER') or 'analise:gis')


@login_required
def gis_pfc(request, pfc_pk, fmt):
    pfc = get_object_or_404(PFC, pk=pfc_pk)
    entries = list(pfc.plan_parcels.select_related('parcel').order_by('number'))
    features = []
    for e in entries:
        for f in gis.parcel_features([e.parcel]):
            f['properties'] = {'id_parc': e.number, 'epoca': e.season, 'objetivo': e.objective, **f['properties']}
            features.append(f)
    return _send(request, features, f'PFC_{pfc.number.replace("/", "-")}', fmt, 'analise:gis')
