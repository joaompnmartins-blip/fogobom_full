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
from .forms import BurningPlanForm, PrePlanForm, selectable_parcels
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
        messages.error(request, 'Esta ação tem um Plano de Queima associado. Elimine primeiro o Plano de Queima.')
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


# ── Planos de Queima ──────────────────────────────────────────────────────────

def _load_vehicles(bp):
    try:
        return json.loads(bp.vehicles or '{}')
    except (TypeError, ValueError):
        return {}


def _parcels_geom(preplan):
    if not preplan:
        return []
    return [{'name': p.name, 'geojson': p.geometry.json}
            for p in preplan.parcels.all() if p.geometry]


def _participant_operatives(action):
    parts = action.participations.filter(confirmed=True)
    if not parts.exists():
        parts = action.participations.filter(intent=Participation.INTENT_VOU).exclude(confirmed=False)
    return list(Operative.objects.filter(user__in=parts.values('user')).values_list('pk', flat=True))


def _bp_form_response(request, bp, preplan, bound=False):
    """Render bp_form.html; when `bound`, re-fill choices from the submitted POST."""
    if bound:
        vehicles = {'VFCI': request.POST.get('vfci', 0), 'VFCM': request.POST.get('vfcm', 0),
                    'Outro': request.POST.get('other_veh', '')}
        selected = _int_list(request.POST.getlist('operatives'))
    else:
        vehicles = _load_vehicles(bp) if bp else {}
        if bp:
            selected = list(bp.operatives.values_list('pk', flat=True))
        else:  # new plan: pre-select the action's confirmed participants (or those who said they'd go)
            selected = _participant_operatives(preplan) if preplan else []
    return render(request, 'fire_actions/bp_form.html', {
        'bp':                  bp,
        'operatives':          Operative.objects.all(),
        'preplan':             preplan,
        'preplans_without_bp': FireAction.objects.filter(burningplan__isnull=True)
                                                 .exclude(status=FireAction.STATUS_CANCELADA),
        'vehicles':            vehicles,
        'selected_operatives': selected,
        'parcels_geom':        _parcels_geom(preplan),
    })


def _save_burning_plan(request, instance, preplan):
    is_new = instance.pk is None
    form = BurningPlanForm(request.POST, instance=instance)
    photos, photo_errors = clean_photos(request.FILES.getlist('photos'))

    if form.is_valid() and not photo_errors:
        with transaction.atomic():
            bp = form.save()
            for photo in photos:
                bp.photos.add(BurningPlanPhoto.objects.create(image=photo))
            # Keep the pre-plan in sync with its burning plan
            pp = bp.pre_plan
            pp.status = FireAction.STATUS_REALIZADA
            pp.execution_date = bp.execution_date
            pp.save()
        messages.success(request, 'Plano de Queima criado com sucesso.' if is_new else 'Plano de Queima atualizado.')
        return redirect('fire_actions:burning_plan_detail', pk=bp.pk)

    form_errors_to_messages(request, form)
    for err in photo_errors:
        messages.error(request, f'Fotografias: {err}')
    if is_new:
        preplan = preplan or form.cleaned_data.get('pre_plan')
    return _bp_form_response(request, form.instance, preplan, bound=True)


@login_required
def burning_plan_list(request):
    plans = BurningPlan.objects.select_related('pre_plan').all()
    return render(request, 'fire_actions/bp_list.html', {'plans': plans})


@login_required
def burning_plan_create(request, preplan_pk=None):
    preplan = get_object_or_404(FireAction, pk=preplan_pk) if preplan_pk else None

    # Guard: already has a burning plan
    if preplan and hasattr(preplan, 'burningplan'):
        messages.warning(request, 'Esta ação já tem um Plano de Queima.')
        return redirect('fire_actions:burning_plan_detail', pk=preplan.burningplan.pk)

    if request.method == 'POST':
        return _save_burning_plan(request, BurningPlan(), preplan)
    return _bp_form_response(request, None, preplan)


@login_required
def burning_plan_detail(request, pk):
    bp = get_object_or_404(BurningPlan.objects.select_related('pre_plan')
                           .prefetch_related('operatives', 'photos', 'pre_plan__parcels'), pk=pk)
    schema_url = bp.tactical_schema.url if bp.tactical_schema else None
    return render(request, 'fire_actions/bp_detail.html',
                  {'bp': bp, 'vehicles': _load_vehicles(bp), 'schema_url': schema_url})


@login_required
def burning_plan_edit(request, pk):
    bp = get_object_or_404(BurningPlan.objects.select_related('pre_plan'), pk=pk)
    if request.method == 'POST':
        return _save_burning_plan(request, bp, bp.pre_plan)
    return _bp_form_response(request, bp, bp.pre_plan)


@staff_required
def burning_plan_delete(request, pk):
    bp = get_object_or_404(BurningPlan, pk=pk)
    if request.method == 'POST':
        pp = bp.pre_plan
        photos = list(bp.photos.all())
        files = [p.image for p in photos] + ([bp.tactical_schema] if bp.tactical_schema else [])
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
        messages.success(request, 'Plano de Queima eliminado.')
        return redirect('fire_actions:burning_plan_list')
    return render(request, 'fire_actions/confirm_delete.html', {'obj': bp, 'tipo': 'Plano de Queima'})


@login_required
def burning_plan_report(request, pk):
    """Generate and return the Word (.docx) report."""
    bp = get_object_or_404(
        BurningPlan.objects.select_related('pre_plan')
                           .prefetch_related('operatives', 'photos', 'pre_plan__parcels'),
        pk=pk
    )
    try:
        from .report import generate_bp_docx
        docx_bytes = generate_bp_docx(bp)
    except Exception:
        logger.exception('Erro ao gerar relatório do plano %s', pk)
        messages.error(request, 'Erro ao gerar o relatório. O problema foi registado.')
        return redirect('fire_actions:burning_plan_detail', pk=pk)
    filename = f"PlanoQueima_{bp.pk}_{bp.execution_date}.docx"
    response = HttpResponse(
        docx_bytes,
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
