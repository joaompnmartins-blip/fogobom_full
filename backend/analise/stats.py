"""Activity statistics: actions, treated area, people and hours, costs, efficacy, problems, monitoring, weather."""
from collections import Counter, defaultdict
from decimal import Decimal

from django.db.models import Avg, Max, Min

from fire_actions.models import ExecutionMember, FireAction, ParcelExecution, WeatherReading
from parcelas.models import FireParcel


def bars(pairs, fmt=lambda v: f'{v:g}'):
    """[(label, value)] -> rows with the bar length as % of the largest value (for single-series bar charts)."""
    pairs = [(label, v) for label, v in pairs if v]
    top = max((float(v) for _, v in pairs), default=0)
    return [{'label': label, 'value': v, 'display': fmt(v), 'pct': round(100 * float(v) / top, 1) if top else 0}
            for label, v in pairs]


def _ha(v):
    return f'{v:,.2f} ha'.replace(',', ' ').replace('.', ',')


def _eur(v):
    return f'{v:,.0f} €'.replace(',', ' ')


def years_available():
    years = {d.year for d in ParcelExecution.objects.values_list('date', flat=True)}
    years |= {d.year for d in FireAction.objects.values_list('scheduled_date', flat=True)}
    return sorted(years, reverse=True)


def compute(year=None):
    from fire_actions.views import _caof_estimate
    from monitorizacao.schedule import all_visits

    ex_qs = ParcelExecution.objects.select_related('parcel', 'plan__pre_plan').prefetch_related(
        'cost_lines', 'members')
    actions = FireAction.objects.all()
    if year:
        ex_qs = ex_qs.filter(date__year=year)
        actions = actions.filter(scheduled_date__year=year)
    executions = list(ex_qs)

    area = sum(ex.area_treated_ha or 0 for ex in executions)
    members = ExecutionMember.objects.filter(execution__in=executions).select_related('execution')
    hours = sum(m.effective_hours or 0 for m in members)
    people = len({m.operative_id for m in members})
    real = sum((ex.cost_total for ex in executions), Decimal('0'))
    estimates = [(_caof_estimate(ex), ex) for ex in executions]
    estimated = sum((e['total'] for e, _ in estimates if e), Decimal('0'))

    by_year = defaultdict(lambda: {'n': 0, 'area': 0.0, 'mato': 0.0, 'pov': 0.0, 'res': 0.0, 'cost': Decimal('0')})
    for ex in executions:
        row = by_year[ex.date.year]
        row['n'] += 1
        row['area'] += ex.area_treated_ha or 0
        row[ex.formation] += ex.area_treated_ha or 0
        row['cost'] += ex.cost_total
    by_concelho = Counter()
    for ex in executions:
        by_concelho[ex.parcel.concelho or '(sem concelho)'] += ex.area_treated_ha or 0
    formations = Counter()
    for ex in executions:
        formations[ex.get_formation_display()] += ex.area_treated_ha or 0
    problems = Counter(code for ex in executions for code in ex.problems_list)
    labels = dict(ParcelExecution.PROBLEMS)
    ratings = Counter(ex.get_rating_objectives_display() for ex in executions if ex.rating_objectives)
    rating_order = [label for _, label in reversed(ParcelExecution._meta.get_field('rating_objectives').choices)]
    types = Counter(('Formação · ' if a.training else '') + a.get_action_type_display()
                    for a in actions.filter(status=FireAction.STATUS_REALIZADA))
    statuses = Counter(a.get_status_display() for a in actions)

    visits = [v for v in all_visits() if not year or v['execution'].date.year == year]
    visit_status = Counter(v['status_label'] for v in visits if v['status'] != 'futura')

    readings = WeatherReading.objects.filter(execution__in=executions)
    weather = readings.aggregate(t_min=Min('temp'), t_avg=Avg('temp'), t_max=Max('temp'), rh_min=Min('rh'),
                                 rh_avg=Avg('rh'), rh_max=Max('rh'), w_min=Min('wind_kmh'), w_avg=Avg('wind_kmh'),
                                 w_max=Max('wind_kmh'))

    parcels = FireParcel.objects.all()
    parcel_status = Counter(p.get_status_display() for p in parcels)
    available_area = sum(p.area_ha or 0 for p in parcels if p.status in FireParcel.AVAILABLE_STATUSES)

    return {
        'kpis': {
            'executions': len(executions), 'burn_days': len({ex.date for ex in executions}),
            'actions_done': actions.filter(status=FireAction.STATUS_REALIZADA).count(),
            'area': area, 'hours': round(hours, 1), 'people': people,
            'incidents': len({ex.plan_id for ex in executions if ex.plan.incident}),
            'real': real, 'estimated': estimated,
            'real_ha': (real / Decimal(str(area))).quantize(Decimal('1')) if area and real else None,
        },
        'by_year': [dict(year=y, **v) for y, v in sorted(by_year.items(), reverse=True)],
        'area_by_concelho': bars(by_concelho.most_common(), _ha),
        'area_by_formation': bars(formations.most_common(), _ha),
        'actions_by_type': bars(types.most_common()),
        'actions_by_status': bars(statuses.most_common()),
        'problems': bars([(labels.get(c, c), n) for c, n in problems.most_common()]),
        'ratings': bars([(label, ratings.get(label, 0)) for label in rating_order]),
        'visits': bars(visit_status.most_common()),
        'weather': weather if readings.exists() else None, 'n_readings': readings.count(),
        'parcels': bars(parcel_status.most_common()), 'available_area': available_area,
        'costs': [{'ex': ex, 'real': ex.cost_total, 'estimate': e['total'] if e else None}
                  for e, ex in estimates if ex.cost_total or e],
    }
