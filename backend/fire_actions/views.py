import json
import logging
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.decorators import staff_required
from core.forms import clean_photos, form_errors_to_messages
from operatives.models import Operative
from parcelas.models import FireParcel
from .forms import (BurningPlanForm, CostFormSet, MemberFormSet, NewParcelExecutionForm, ParcelExecutionForm,
                    PrePlanForm, ReadingFormSet, StripFormSet, selectable_parcels)
from .models import BurningPlan, BurningPlanPhoto, FireAction, Participation
from .notify import notify_action_update, notify_new_action
from .outlook import action_outlook

logger = logging.getLogger(__name__)


def _int_list(values):
    return [int(v) for v in values if str(v).isdigit()]


def _is_tecnico(user):
    op = getattr(user, 'operative', None)
    return bool(op and op.is_tecnico)


def can_manage(user, action):
    """Creator, responsible technician, any validated technician and staff manage an action."""
    return (user.is_staff or _is_tecnico(user) or action.created_by_id == user.pk
            or action.responsible_user_id == user.pk)


# ── Ações ────────────────────────────────────────────────────────────────────

@login_required
def preplan_list(request):
    actions = FireAction.objects.prefetch_related('parcels').select_related('responsible_user') \
        .annotate(n_part=Count('participations', filter=~Q(participations__intent=Participation.INTENT_NAO)))
    status = request.GET.get('status', '')
    if status:
        actions = actions.filter(status=status)
    return render(request, 'fire_actions/preplan_list.html', {
        'actions': actions, 'status': status, 'statuses': FireAction.STATUS_CHOICES})


@login_required
def announcements(request):
    """Upcoming open actions, with outlook and sign-up — visible to every user."""
    today = timezone.localdate()
    actions = list(FireAction.objects.filter(status__in=FireAction.OPEN_STATUSES, scheduled_date__gte=today)
                   .order_by('scheduled_date', 'start_time').prefetch_related('parcels')
                   .select_related('responsible_user', 'responsible_user__operative'))
    mine = dict(Participation.objects.filter(user=request.user, action__in=actions)
                .values_list('action_id', 'intent'))
    for a in actions:
        a.outlook = action_outlook(a)
        a.my_intent = mine.get(a.pk)
        a.n_part = a.participations.exclude(intent=Participation.INTENT_NAO).count()
    return render(request, 'fire_actions/announcements.html', {'actions': actions, 'today': today})


def _form_context(form, action=None):
    return {
        'form': form,
        'action_obj': action if action and action.pk else None,
        'parcelas': selectable_parcels(action),
        'selected_parcels': _int_list(form.data.getlist('parcels')) if form.is_bound
                            else list(action.parcels.values_list('pk', flat=True)) if action and action.pk else [],
    }


def _save_preplan(request, instance):
    is_new = instance.pk is None
    before = (instance.scheduled_date, instance.start_time) if not is_new else None
    form = PrePlanForm(request.POST, request.FILES, instance=instance)
    if form.is_valid():
        action = form.save(commit=False)
        if is_new:
            action.created_by = request.user
        action.save()
        form.save_m2m()
        if is_new:
            notify_new_action(request, action)
            messages.success(request, f'Ação "{action.name}" anunciada.')
        else:
            if before != (action.scheduled_date, action.start_time):
                notify_action_update(request, action, 'Data ou hora alterada')
            messages.success(request, f'Ação "{action.name}" atualizada.')
        return redirect('fire_actions:detail', pk=action.pk)
    form_errors_to_messages(request, form)
    return render(request, 'fire_actions/preplan_form.html', _form_context(form, instance))


@login_required
def preplan_create(request):
    if request.method == 'POST':
        return _save_preplan(request, FireAction())
    initial = {}
    if _is_tecnico(request.user):
        initial['responsible_user'] = request.user.pk
    return render(request, 'fire_actions/preplan_form.html', _form_context(PrePlanForm(initial=initial)))


@login_required
def preplan_edit(request, pk):
    action = get_object_or_404(FireAction, pk=pk)
    if not can_manage(request.user, action):
        messages.error(request, 'Só quem criou a ação, o técnico responsável, os técnicos e os administradores a podem editar.')
        return redirect('fire_actions:detail', pk=pk)
    if request.method == 'POST':
        return _save_preplan(request, action)
    return render(request, 'fire_actions/preplan_form.html', _form_context(PrePlanForm(instance=action), action))


@staff_required
def preplan_delete(request, pk):
    action = get_object_or_404(FireAction, pk=pk)
    if hasattr(action, 'burningplan'):
        messages.error(request, 'Esta ação tem uma execução (POQ) registada. Elimine primeiro a execução.')
        return redirect('fire_actions:detail', pk=pk)
    if request.method == 'POST':
        name = action.name
        action.delete()
        messages.success(request, f'Ação "{name}" eliminada.')
        return redirect('fire_actions:list')
    return render(request, 'fire_actions/confirm_delete.html', {'obj': action, 'tipo': 'Ação'})


@login_required
def preplan_detail(request, pk):
    action = get_object_or_404(FireAction.objects.select_related('responsible_user', 'responsible_user__operative',
                                                                  'created_by'), pk=pk)
    outlooks = []
    if action.is_open:
        outlooks = [action_outlook(action, d) for d in
                    [action.scheduled_date, action.alt_date_1, action.alt_date_2] if d]
    participations = list(action.participations.select_related('user', 'user__operative'))
    parcels = list(action.parcels.all())
    return render(request, 'fire_actions/preplan_detail.html', {
        'action': action,
        'has_bp': hasattr(action, 'burningplan'),
        'outlooks': outlooks,
        'participations': [p for p in participations if p.intent != Participation.INTENT_NAO],
        'my_part': next((p for p in participations if p.user_id == request.user.pk), None),
        'can_manage': can_manage(request.user, action),
        'roles': Participation.ROLES,
        'today': timezone.localdate(),
        'map_data': {
            'parcels': [{'name': p.name, 'geojson': json.loads(p.geometry.json)} for p in parcels],
            'meeting': [action.meeting_point.y, action.meeting_point.x] if action.meeting_point else None,
        },
    })


@require_POST
@login_required
def action_status(request, pk):
    action = get_object_or_404(FireAction, pk=pk)
    if not can_manage(request.user, action):
        messages.error(request, 'Sem permissão para alterar o estado desta ação.')
        return redirect('fire_actions:detail', pk=pk)
    new = request.POST.get('status')
    reason = request.POST.get('reason', '').strip()
    if new == FireAction.STATUS_CONFIRMADA:
        outlook = action_outlook(action)
        if outlook['blocked']:
            messages.error(request, 'Não é possível confirmar: perigo de incêndio rural «muito elevado» ou «máximo» '
                                    'num dos concelhos (a queima não é permitida).')
            return redirect('fire_actions:detail', pk=pk)
        if action.legal_missing:
            messages.error(request, 'Complete o enquadramento legal antes de confirmar: ' + '; '.join(action.legal_missing))
            return redirect('fire_actions:detail', pk=pk)
        action.status, action.status_reason, what = new, '', 'Ação confirmada'
    elif new == FireAction.STATUS_ADIADA:
        new_date = request.POST.get('new_date')
        try:
            d = datetime.strptime(new_date, '%Y-%m-%d').date() if new_date else None
        except ValueError:
            d = None
        if d:
            action.scheduled_date = d
            action.status, what = FireAction.STATUS_PREVISTA, f'Ação adiada para {d:%d/%m/%Y}'
        else:
            action.status, what = FireAction.STATUS_ADIADA, 'Ação adiada (nova data a definir)'
        action.status_reason = reason
    elif new == FireAction.STATUS_CANCELADA:
        if not reason:
            messages.error(request, 'Indique o motivo do cancelamento.')
            return redirect('fire_actions:detail', pk=pk)
        action.status, action.status_reason, what = new, reason, 'Ação cancelada'
    elif new == FireAction.STATUS_PREVISTA and action.status in (FireAction.STATUS_CANCELADA, FireAction.STATUS_ADIADA):
        action.status, action.status_reason, what = new, '', 'Ação reaberta'
    else:
        return redirect('fire_actions:detail', pk=pk)
    action.save()
    notify_action_update(request, action, what)
    messages.success(request, what + '.')
    return redirect('fire_actions:detail', pk=pk)


@require_POST
@login_required
def participate(request, pk):
    action = get_object_or_404(FireAction, pk=pk)
    if not action.is_open:
        messages.error(request, 'As inscrições estão fechadas para esta ação.')
        return redirect('fire_actions:detail', pk=pk)
    intent = request.POST.get('intent', Participation.INTENT_VOU)
    if intent not in dict(Participation.INTENTS):
        intent = Participation.INTENT_VOU
    role = request.POST.get('role', '')
    if role not in dict(Participation.ROLES):
        role = ''
    part, created = Participation.objects.get_or_create(action=action, user=request.user)
    part.intent, part.role, part.note = intent, role, request.POST.get('note', '')[:200]
    if intent == Participation.INTENT_NAO:
        part.confirmed = None
    part.save()
    messages.success(request, {'vou': 'Inscrição registada.', 'talvez': 'Registado como "talvez".',
                               'nao': 'Registado que não vai participar.'}[intent])
    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('fire_actions:detail', pk=pk)


@require_POST
@login_required
def participant_decision(request, pk, part_pk):
    action = get_object_or_404(FireAction, pk=pk)
    part = get_object_or_404(Participation, pk=part_pk, action=action)
    if not can_manage(request.user, action):
        messages.error(request, 'Só quem gere a ação pode confirmar participantes.')
        return redirect('fire_actions:detail', pk=pk)
    decision = request.POST.get('decision')
    if decision == 'confirmar':
        if action.slots and action.confirmed_participants().exclude(pk=part.pk).count() >= action.slots:
            messages.error(request, f'Todas as {action.slots} vagas já estão preenchidas.')
            return redirect('fire_actions:detail', pk=pk)
        part.confirmed = True
    elif decision == 'recusar':
        part.confirmed = False
    else:
        part.confirmed = None
    part.save(update_fields=['confirmed', 'updated_at'])
    if part.user.email and decision in ('confirmar', 'recusar'):
        from core.emails import send_async
        send_async(f'[Fogo Bom] Participação {"confirmada" if part.confirmed else "não confirmada"}: {action.name}',
                   f'A sua participação na ação "{action.name}" ({action.scheduled_date:%d/%m/%Y}) foi '
                   f'{"confirmada" if part.confirmed else "não confirmada"} pelo técnico.\n\n'
                   + request.build_absolute_uri(f'/acoes/{action.pk}/'),
                   [part.user.email])
    return redirect('fire_actions:detail', pk=pk)


@require_POST
@login_required
def action_communication(request, pk):
    """Record when the start / end of the operation was communicated to civil protection."""
    action = get_object_or_404(FireAction, pk=pk)
    if not can_manage(request.user, action):
        messages.error(request, 'Sem permissão.')
        return redirect('fire_actions:detail', pk=pk)
    which = request.POST.get('which')
    now = timezone.now()
    if which == 'inicio' and not action.comm_start_at:
        action.comm_start_at, action.comm_start_by = now, request.user
    elif which == 'fim' and action.comm_start_at and not action.comm_end_at:
        action.comm_end_at, action.comm_end_by = now, request.user
    else:
        return redirect('fire_actions:detail', pk=pk)
    action.save()
    messages.success(request, f'Registado: {"início" if which == "inicio" else "fim"} comunicado às '
                              f'{timezone.localtime(now):%H:%M}.')
    return redirect('fire_actions:detail', pk=pk)


@login_required
def action_ics(request, pk):
    """Calendar file (.ics) for the action."""
    action = get_object_or_404(FireAction, pk=pk)
    url = request.build_absolute_uri(f'/acoes/{action.pk}/')
    if action.start_time:
        start = timezone.make_aware(datetime.combine(action.scheduled_date, action.start_time))
        end = start + timedelta(hours=6)
        fmt = lambda dt: dt.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        when = f'DTSTART:{fmt(start)}\r\nDTEND:{fmt(end)}'
    else:
        when = (f'DTSTART;VALUE=DATE:{action.scheduled_date:%Y%m%d}\r\n'
                f'DTEND;VALUE=DATE:{action.scheduled_date + timedelta(days=1):%Y%m%d}')
    esc = lambda t: t.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')
    location = action.meeting_notes or ', '.join(p.name for p in action.parcels.all())
    if action.meeting_point:
        location += f' ({action.meeting_point.y:.5f}, {action.meeting_point.x:.5f})'
    body = '\r\n'.join([
        'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Fogo Bom Algarve//PT', 'CALSCALE:GREGORIAN', 'BEGIN:VEVENT',
        f'UID:acao-{action.pk}@fogobomalgarve.com', f'DTSTAMP:{timezone.now():%Y%m%dT%H%M%SZ}', when,
        f'SUMMARY:{esc(action.get_action_type_display() + ": " + action.name)}',
        f'LOCATION:{esc(location)}', f'DESCRIPTION:{esc("Estado: " + action.get_status_display() + chr(10) + url)}',
        f'URL:{url}', 'END:VEVENT', 'END:VCALENDAR', ''])
    response = HttpResponse(body, content_type='text/calendar; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="acao-{action.pk}.ics"'
    return response


# ── Execução (POQ-Execução) ──────────────────────────────────────────────────

ROLE_TO_FUNCTION = {'responsavel': 'coordenacao', 'ignicao': 'ignicao', 'seguranca': 'seguranca',
                    'vigia': 'vigilancia', 'apoio': 'apoio', 'observador': 'formacao'}


def _create_execution(plan, parcel, d):
    """New parcel execution pre-filled with the action's participants and the 4 safety strip sides."""
    from .models import ExecutionMember, ParcelExecution, SafetyStrip
    action = plan.pre_plan
    ex = ParcelExecution.objects.create(
        plan=plan, parcel=parcel, date=d, area_treated_ha=parcel.area_ha,
        formation='mato' if parcel.vegetation_type == 'matos' else 'pov')
    parts = action.participations.filter(confirmed=True)
    if not parts.exists():
        parts = action.participations.filter(intent=Participation.INTENT_VOU).exclude(confirmed=False)
    roles = dict(parts.values_list('user_id', 'role'))
    for op in Operative.objects.filter(user__in=parts.values('user')):
        ExecutionMember.objects.create(execution=ex, operative=op, function=ROLE_TO_FUNCTION.get(roles.get(op.user_id), ''))
    responsible = getattr(action.responsible_user, 'operative', None) if action.responsible_user_id else None
    if responsible and not ex.members.filter(operative=responsible).exists():
        ExecutionMember.objects.create(execution=ex, operative=responsible, function='coordenacao')
    for side, _ in SafetyStrip.SIDES:
        SafetyStrip.objects.create(execution=ex, side=side)
    ex.n_men = ex.members.count() or None
    ex.save(update_fields=['n_men'])
    return ex


def _sync_action(plan):
    """Keep the action realizada with the first execution date."""
    first = plan.executions.order_by('date').values_list('date', flat=True).first() or plan.execution_date
    if plan.execution_date != first:
        plan.execution_date = first
        plan.save(update_fields=['execution_date'])
    action = plan.pre_plan
    action.status, action.execution_date = FireAction.STATUS_REALIZADA, first
    action.save()


def _require_manage(request, action):
    if not can_manage(request.user, action):
        messages.error(request, 'Só quem gere a ação (técnico responsável, técnicos ou quem a anunciou) pode registar a execução.')
        return False
    return True


@login_required
def burning_plan_list(request):
    plans = BurningPlan.objects.select_related('pre_plan').prefetch_related('executions')
    return render(request, 'fire_actions/bp_list.html', {'plans': plans})


@login_required
def burning_plan_create(request, preplan_pk=None):
    preplan = get_object_or_404(FireAction, pk=preplan_pk) if preplan_pk else None
    if preplan and hasattr(preplan, 'burningplan'):
        messages.warning(request, 'Esta ação já tem a execução registada.')
        return redirect('fire_actions:burning_plan_detail', pk=preplan.burningplan.pk)
    if preplan and not _require_manage(request, preplan):
        return redirect('fire_actions:detail', pk=preplan.pk)

    if request.method == 'POST':
        data = request.POST.copy()
        if preplan:
            data['pre_plan'] = preplan.pk
        form = BurningPlanForm(data)
        if form.is_valid():
            action = form.cleaned_data['pre_plan']
            if not _require_manage(request, action):
                return redirect('fire_actions:detail', pk=action.pk)
            with transaction.atomic():
                plan = form.save()
                for parcel in action.parcels.all():
                    _create_execution(plan, parcel, plan.execution_date)
                _sync_action(plan)
            messages.success(request, 'Execução registada. Preencha agora os dados de cada parcela.')
            return redirect('fire_actions:burning_plan_detail', pk=plan.pk)
        form_errors_to_messages(request, form)
    else:
        form = BurningPlanForm(initial={'pre_plan': preplan.pk if preplan else None,
                                        'execution_date': (preplan.scheduled_date if preplan else timezone.localdate())})
    return render(request, 'fire_actions/bp_form.html', {'form': form, 'bp': None, 'preplan': preplan})


@login_required
def burning_plan_edit(request, pk):
    plan = get_object_or_404(BurningPlan.objects.select_related('pre_plan'), pk=pk)
    if not _require_manage(request, plan.pre_plan):
        return redirect('fire_actions:burning_plan_detail', pk=pk)
    if request.method == 'POST':
        form = BurningPlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, 'Execução atualizada.')
            return redirect('fire_actions:burning_plan_detail', pk=pk)
        form_errors_to_messages(request, form)
    else:
        form = BurningPlanForm(instance=plan)
    return render(request, 'fire_actions/bp_form.html', {'form': form, 'bp': plan, 'preplan': plan.pre_plan})


def _caof_estimate(ex):
    """CAOF estimate for the parcel (from its PFC entry, or from its evaluation)."""
    from pfc.costs import default_inputs, parcel_estimate
    from pfc.models import PFCParcel
    action = ex.plan.pre_plan
    pp = PFCParcel.objects.filter(pfc_id=action.pfc_id, parcel=ex.parcel).first() if action.pfc_id else None
    if pp is None:
        pp = PFCParcel(parcel=ex.parcel, number=0, **default_inputs(ex.parcel))
    try:
        return parcel_estimate(pp)
    except Exception:
        logger.warning('Estimativa CAOF indisponível', exc_info=True)
        return None


def reading_issues(ex):
    """{reading_id: [issues]} for readings outside the PFC prescription of the parcel."""
    from pfc.models import PFCParcel
    action = ex.plan.pre_plan
    pp = PFCParcel.objects.filter(pfc_id=action.pfc_id, parcel=ex.parcel).first() if action.pfc_id else None
    if not pp:
        return {}
    out = {}
    for r in ex.readings.all():
        issues = []
        for label, value, lo, hi, unit in [('temperatura', r.temp, pp.temp_min, pp.temp_max, '°C'),
                                           ('HR', r.rh, pp.rh_min, pp.rh_max, '%'),
                                           ('vento', r.wind_kmh, pp.wind_min, pp.wind_max, 'km/h'),
                                           ('propagação', r.spread_m_min, pp.spread_min, pp.spread_max, 'm/min'),
                                           ('chama', r.flame_length_m, pp.flame_min, pp.flame_max, 'm')]:
            if value is None:
                continue
            if lo is not None and value < lo:
                issues.append(f'{label} {value:g}{unit} < {lo:g}')
            elif hi is not None and value > hi:
                issues.append(f'{label} {value:g}{unit} > {hi:g}')
        if issues:
            out[r.pk] = issues
    return out


@login_required
def burning_plan_detail(request, pk):
    plan = get_object_or_404(BurningPlan.objects.select_related('pre_plan', 'pre_plan__pfc'), pk=pk)
    from monitorizacao.schedule import expected_visits
    executions = list(plan.executions.select_related('parcel').prefetch_related(
        'members__operative', 'readings', 'cost_lines', 'assessments', 'waivers'))
    rows = []
    for ex in executions:
        est = _caof_estimate(ex)
        rows.append({'ex': ex, 'estimate': est, 'issues': reading_issues(ex), 'real': ex.cost_total,
                     'visits': expected_visits(ex)})
    photos = plan.photos.select_related('parcel').order_by('parcel__name', 'moment', 'pk')
    action = plan.pre_plan
    return render(request, 'fire_actions/bp_detail.html', {
        'bp': plan, 'action': action, 'rows': rows, 'photos': photos,
        'can_manage': can_manage(request.user, action),
        'add_form': NewParcelExecutionForm(plan=plan, initial={'date': plan.execution_date}),
        'burn_period': _burn_period(executions or [plan]),
        'today': timezone.localdate(),
        'icnf_rows': _icnf_rows(plan, executions),
    })


def _icnf_rows(plan, executions):
    from registos.deadlines import INCIDENT_DAYS, icnf_window_after
    last = max((ex.date for ex in executions), default=plan.execution_date)
    first = min((ex.date for ex in executions), default=plan.execution_date)
    if plan.incident:
        due = (plan.incident_date or first) + timedelta(days=INCIDENT_DAYS)
        rule = f'Fuga do fogo: no prazo de 15 dias, até {due:%d/%m/%Y}.'
    else:
        start, due = icnf_window_after(last)
        rule = f'Com a base de dados, na 1.ª quinzena de {start:%m/%Y} (até {due:%d/%m/%Y}).'
    return [('poq', 'POQ-Execução', plan.poq_sent_on, rule),
            ('impacto', 'POQ-Impacto', plan.impact_sent_on, f'Até 31/07/{first.year + 1}.')]


def _burn_period(items):
    """POQ header: 1 Jan – 31 May or 1 Oct – 31 Dec of the year of execution."""
    dates = [getattr(i, 'date', None) or getattr(i, 'execution_date', None) for i in items]
    dates = [d for d in dates if d]
    if not dates:
        return ''
    d = min(dates)
    if d.month <= 5:
        return f'1 de janeiro a 31 de maio de {d.year}'
    if d.month >= 10:
        return f'1 de outubro a 31 de dezembro de {d.year}'
    return f'fora dos períodos de queima habituais ({d:%d/%m/%Y})'


@require_POST
@login_required
def execution_add(request, pk):
    plan = get_object_or_404(BurningPlan, pk=pk)
    if not _require_manage(request, plan.pre_plan):
        return redirect('fire_actions:burning_plan_detail', pk=pk)
    form = NewParcelExecutionForm(request.POST, plan=plan)
    if form.is_valid():
        ex = _create_execution(plan, form.cleaned_data['parcel'], form.cleaned_data['date'])
        _sync_action(plan)
        return redirect('fire_actions:execution_edit', pk=ex.pk)
    form_errors_to_messages(request, form)
    return redirect('fire_actions:burning_plan_detail', pk=pk)


@login_required
def execution_edit(request, pk):
    from .models import ParcelExecution
    ex = get_object_or_404(ParcelExecution.objects.select_related('plan', 'plan__pre_plan', 'parcel'), pk=pk)
    plan = ex.plan
    if not _require_manage(request, plan.pre_plan):
        return redirect('fire_actions:burning_plan_detail', pk=plan.pk)
    if request.method == 'POST':
        form = ParcelExecutionForm(request.POST, request.FILES, instance=ex)
        formsets = {
            'members': MemberFormSet(request.POST, instance=ex, prefix='members'),
            'readings': ReadingFormSet(request.POST, instance=ex, prefix='readings'),
            'strips': StripFormSet(request.POST, instance=ex, prefix='strips'),
            'costs': CostFormSet(request.POST, instance=ex, prefix='costs'),
        }
        photos, photo_errors = clean_photos(request.FILES.getlist('photos'))
        if form.is_valid() and all(fs.is_valid() for fs in formsets.values()) and not photo_errors:
            with transaction.atomic():
                form.save()
                for fs in formsets.values():
                    fs.save()
                moment = request.POST.get('photo_moment', '')
                for photo in photos:
                    plan.photos.add(BurningPlanPhoto.objects.create(
                        image=photo, parcel=ex.parcel, taken_on=ex.date,
                        moment=moment if moment in dict(BurningPlanPhoto.MOMENTS) else '',
                        caption=request.POST.get('photo_caption', '')[:200]))
            messages.success(request, f'Execução de {ex.parcel.name} ({ex.date:%d/%m/%Y}) guardada.')
            if request.POST.get('stay'):
                return redirect('fire_actions:execution_edit', pk=ex.pk)
            return redirect('fire_actions:burning_plan_detail', pk=plan.pk)
        form_errors_to_messages(request, form)
        for name, fs in formsets.items():
            for i, errs in enumerate(fs.errors):
                for field, msgs in errs.items():
                    messages.error(request, f'{name} — linha {i + 1}: {"; ".join(msgs)}')
            for err in fs.non_form_errors():
                messages.error(request, f'{name}: {err}')
        for err in photo_errors:
            messages.error(request, f'Fotografias: {err}')
    else:
        form = ParcelExecutionForm(instance=ex)
        formsets = {
            'members': MemberFormSet(instance=ex, prefix='members'),
            'readings': ReadingFormSet(instance=ex, prefix='readings'),
            'strips': StripFormSet(instance=ex, prefix='strips'),
            'costs': CostFormSet(instance=ex, prefix='costs'),
        }
    issues = reading_issues(ex)
    for f in formsets['readings']:
        f.issue_text = '; '.join(issues.get(f.instance.pk, [])) if f.instance.pk else ''
    return render(request, 'fire_actions/execution_form.html', {
        'ex': ex, 'plan': plan, 'form': form, **formsets,
        'issues': issues, 'estimate': _caof_estimate(ex),
        'photo_moments': BurningPlanPhoto.MOMENTS,
        'ex_photos': plan.photos.filter(parcel=ex.parcel, taken_on=ex.date),
    })


@require_POST
@login_required
def execution_delete(request, pk):
    from .models import ParcelExecution
    ex = get_object_or_404(ParcelExecution.objects.select_related('plan', 'plan__pre_plan'), pk=pk)
    plan = ex.plan
    if not _require_manage(request, plan.pre_plan):
        return redirect('fire_actions:burning_plan_detail', pk=plan.pk)
    if ex.assessments.exists():
        messages.error(request, 'Esta execução já tem avaliações de impacto / monitorização. '
                                'Peça a um administrador para as eliminar primeiro.')
        return redirect('fire_actions:execution_edit', pk=ex.pk)
    ex.delete()
    _sync_action(plan)
    messages.success(request, 'Execução da parcela eliminada.')
    return redirect('fire_actions:burning_plan_detail', pk=plan.pk)


@staff_required
def burning_plan_delete(request, pk):
    bp = get_object_or_404(BurningPlan, pk=pk)
    if request.method == 'POST':
        if bp.executions.filter(assessments__isnull=False).exists():
            messages.error(request, 'Esta execução tem avaliações de impacto / monitorização. Elimine-as primeiro.')
            return redirect('fire_actions:burning_plan_detail', pk=pk)
        pp = bp.pre_plan
        photos = list(bp.photos.all())
        files = [p.image for p in photos] + ([bp.tactical_schema] if bp.tactical_schema else []) \
            + [ex.schema for ex in bp.executions.all() if ex.schema]
        with transaction.atomic():
            bp.delete()
            for p in photos:
                p.delete()
            pp.status = FireAction.STATUS_PREVISTA
            pp.execution_date = None
            pp.save()
        # Remove stored files only after the DB changes are committed
        for f in files:
            try:
                f.delete(save=False)
            except Exception:
                logger.warning('Não foi possível apagar o ficheiro %s', f.name, exc_info=True)
        messages.success(request, 'Execução eliminada.')
        return redirect('fire_actions:burning_plan_list')
    return render(request, 'fire_actions/confirm_delete.html', {'obj': bp, 'tipo': 'Execução'})


@login_required
def burning_plan_report(request, pk):
    """POQ-Execução (.docx) following the ICNF model."""
    plan = get_object_or_404(BurningPlan.objects.select_related('pre_plan', 'pre_plan__pfc'), pk=pk)
    try:
        from .poq import generate_poq_execucao
        docx_bytes = generate_poq_execucao(plan)
    except Exception:
        logger.exception('Erro ao gerar o POQ-Execução %s', pk)
        messages.error(request, 'Erro ao gerar o documento. O problema foi registado.')
        return redirect('fire_actions:burning_plan_detail', pk=pk)
    ref = plan.pre_plan.pfc.number.replace('/', '-') if plan.pre_plan.pfc_id else plan.pre_plan.name[:40]
    response = HttpResponse(docx_bytes,
                            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    response['Content-Disposition'] = f'attachment; filename="POQ-Execucao_{ref}_{plan.execution_date}.docx"'
    return response
