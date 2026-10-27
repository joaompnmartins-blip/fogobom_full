"""Legal deadlines (Regulamento do Fogo Técnico, 2014) and monitoring visits, per responsible user."""
from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from fire_actions.models import BurningPlan
from monitorizacao.schedule import UPCOMING_DAYS, all_visits
from operatives.models import Operative
from pfc.models import PFC

ICNF_MONTHS = (2, 4, 6, 12)    # POQ + database file: first fortnight of February, April, June and December
INCIDENT_DAYS = 15             # POQ after a fire escape (art. 14.º n.º 5)
URGENT_DAYS = 15
HORIZON_DAYS = 120             # how far ahead the list looks
PFC_END_NOTICE_DAYS = 90

KIND_LABELS = {'poq': 'Envio do POQ-Execução e da base de dados ao ICNF', 'incidente': 'POQ com fuga do fogo',
               'impacto': 'Envio do POQ-Impacto ao ICNF', 'monitorizacao': 'Visita de monitorização',
               'credenciacao': 'Renovação da credenciação', 'pfc': 'Fim da validade do PFC'}


def icnf_window_after(d):
    """First ICNF submission window (1–15 of Feb/Apr/Jun/Dec) that starts after `d`: (start, end)."""
    for year in (d.year, d.year + 1):
        for m in ICNF_MONTHS:
            start = date(year, m, 1)
            if start > d:
                return start, date(year, m, 15)
    raise AssertionError('unreachable')


def _responsible(action):
    return action.responsible_user_id or action.created_by_id


def _item(kind, title, due, url, users, today, detail='', start=None):
    days = (due - today).days
    status = 'atrasado' if days < 0 else 'urgente' if days <= URGENT_DAYS else 'proximo'
    return {'kind': kind, 'kind_label': KIND_LABELS[kind], 'title': title, 'due': due, 'start': start,
            'days': days, 'overdue_days': max(0, -days), 'status': status, 'url': url, 'users': {u for u in users if u}, 'detail': detail,
            'key': f'{kind}:{url}:{due:%Y%m%d}'}


def all_deadlines(today=None):
    today = today or timezone.localdate()
    horizon = today + timedelta(days=HORIZON_DAYS)
    items = []

    plans = BurningPlan.objects.select_related('pre_plan').prefetch_related('executions')
    for plan in plans:
        action = plan.pre_plan
        url = reverse('fire_actions:burning_plan_detail', args=[plan.pk])
        dates = [ex.date for ex in plan.executions.all()] or [plan.execution_date]
        first, last = min(dates), max(dates)
        users = [_responsible(action)]
        if not plan.poq_sent_on:
            if plan.incident:
                due = (plan.incident_date or first) + timedelta(days=INCIDENT_DAYS)
                items.append(_item('incidente', action.name, due, url, users, today,
                                   'Fuga do fogo: o POQ tem de ser enviado no prazo de 15 dias.'))
            else:
                start, due = icnf_window_after(last)
                items.append(_item('poq', action.name, due, url, users, today,
                                   f'1.ª quinzena de {start:%m/%Y}, com o ficheiro da base de dados (Excel).',
                                   start=start))
        if not plan.impact_sent_on:
            items.append(_item('impacto', action.name, date(first.year + 1, 7, 31), url, users, today,
                               'Até 31 de julho do ano seguinte à queima.'))

    for v in all_visits(today):
        if v['status'] not in ('atrasada', 'em_curso', 'futura'):
            continue
        if v['status'] == 'futura' and (v['due'] - today).days > UPCOMING_DAYS:
            continue
        ex = v['execution']
        url = reverse('monitorizacao:create', args=[ex.pk]) + f'?fase={v["phase"]}&ano={v["year"]}'
        items.append(_item('monitorizacao', f'{ex.parcel.name} — {v["label"]}', v['deadline'], url,
                           [_responsible(ex.plan.pre_plan)], today,
                           f'Queima de {ex.date:%d/%m/%Y}; visita prevista para {v["due"]:%d/%m/%Y}.',
                           start=v['due']))

    for op in Operative.objects.filter(credential_lifetime=False, credential_valid_until__isnull=False) \
            .exclude(credential_type=Operative.CRED_NENHUMA).exclude(credential_status=Operative.STATUS_RECUSADA):
        end = op.credential_valid_until
        start = end - timedelta(days=61)
        if end < today - timedelta(days=30) or start > horizon:
            continue
        items.append(_item('credenciacao', op.name, end, reverse('registos:fieldbook', args=[op.pk]),
                           [op.user_id], today,
                           f'A renovação é pedida ao ICNF a partir de {start:%d/%m/%Y} (2 meses antes do fim).',
                           start=start))

    for pfc in PFC.objects.filter(status=PFC.STATUS_APROVADO, validity_end__lte=today + timedelta(
            days=PFC_END_NOTICE_DAYS), validity_end__gte=today - timedelta(days=30)):
        items.append(_item('pfc', f'PFC {pfc.number} — {pfc.name}', pfc.validity_end,
                           reverse('pfc:detail', args=[pfc.pk]), [pfc.technician_id], today,
                           'Depois desta data não podem ser feitas queimas ao abrigo deste plano.'))

    items = [i for i in items if i['due'] <= horizon or i['status'] == 'atrasado']
    items.sort(key=lambda i: (i['due'], i['kind']))
    return items


def deadlines_for(user, today=None):
    return [i for i in all_deadlines(today) if user.pk in i['users']]
