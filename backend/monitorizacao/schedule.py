"""Monitoring calendar of a parcel execution: immediate assessment, 6 months, then yearly while the parcel
is not burned again."""
import calendar
from datetime import date, timedelta

from django.utils import timezone

from fire_actions.models import ParcelExecution
from .models import Assessment

IMMEDIATE_DAYS = 30      # 1.ª fase: within a month of the burn
WINDOW_DAYS = 60         # 6 months / annual visits: up to two months after the due date
UPCOMING_DAYS = 60       # "próximas" in the monitoring list

STATUS_LABELS = {'feita': 'Realizada', 'dispensada': 'Dispensada', 'atrasada': 'Em atraso', 'em_curso': 'A realizar',
                 'futura': 'Prevista'}


def add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _visit(ex, phase, year, due, deadline, done, today, waived=None):
    a = done.get((phase, year))
    w = None if a else (waived or {}).get((phase, year))
    status = 'feita' if a else 'dispensada' if w else 'atrasada' if today > deadline else \
        'em_curso' if today >= due else 'futura'
    label = f'Monitorização — ano {year}' if phase == Assessment.PHASE_ANUAL else dict(Assessment.PHASES)[phase]
    return {'execution': ex, 'phase': phase, 'year': year, 'due': due, 'deadline': deadline, 'assessment': a,
            'waiver': w, 'status': status, 'status_label': STATUS_LABELS[status], 'label': label}


def next_burn(ex):
    """Date of the next burn of the same parcel in another execution (ends the monitoring cycle), or None."""
    return (ParcelExecution.objects.filter(parcel_id=ex.parcel_id, date__gt=ex.date).exclude(plan_id=ex.plan_id)
            .order_by('date').values_list('date', flat=True).first())


def is_continuation(ex):
    """A later day of the same parcel in the same execution: monitored with the first day."""
    return ParcelExecution.objects.filter(plan_id=ex.plan_id, parcel_id=ex.parcel_id, date__lt=ex.date).exists()


def expected_visits(ex, today=None, until=None, continuation=None):
    """Visits expected for this execution, up to and including the next future one.

    `until` (date of the next burn of the parcel, False for none) and `continuation` can be passed to avoid
    queries per execution.
    """
    today = today or timezone.localdate()
    if is_continuation(ex) if continuation is None else continuation:
        return []
    until = next_burn(ex) if until is None else until or None
    done = {(a.phase, a.year): a for a in ex.assessments.all()}
    waived = {(w.phase, w.year): w for w in ex.waivers.all()}
    visits = [_visit(ex, Assessment.PHASE_IMEDIATA, 0, ex.date, ex.date + timedelta(days=IMMEDIATE_DAYS), done,
                     today, waived)]
    due = add_months(ex.date, 6)
    if not until or due < until:
        visits.append(_visit(ex, Assessment.PHASE_6M, 0, due, due + timedelta(days=WINDOW_DAYS), done, today,
                             waived))
    year = 1
    while True:
        due = add_months(ex.date, 12 * year)
        if until and due >= until:
            break
        visits.append(_visit(ex, Assessment.PHASE_ANUAL, year, due, due + timedelta(days=WINDOW_DAYS), done, today,
                             waived))
        if due > today:
            break
        year += 1
    # Annual visits recorded beyond the computed horizon still show up
    shown = {(v['phase'], v['year']) for v in visits}
    for (phase, y), a in sorted(done.items()):
        if (phase, y) not in shown:
            d = add_months(ex.date, 12 * y) if phase == Assessment.PHASE_ANUAL else a.date
            visits.append(_visit(ex, phase, y, d, d + timedelta(days=WINDOW_DAYS), done, today))
    return visits


def all_visits(today=None):
    """Expected visits of every execution (three queries: executions, assessments and waivers)."""
    today = today or timezone.localdate()
    executions = list(ParcelExecution.objects.select_related('parcel', 'plan__pre_plan')
                      .prefetch_related('assessments', 'waivers').order_by('parcel_id', 'date'))
    out = []
    for ex in executions:
        same_parcel = [e for e in executions if e.parcel_id == ex.parcel_id]
        continuation = any(e.plan_id == ex.plan_id and e.date < ex.date for e in same_parcel)
        until = min((e.date for e in same_parcel if e.date > ex.date and e.plan_id != ex.plan_id), default=False)
        out.extend(expected_visits(ex, today, until, continuation))
    return out
