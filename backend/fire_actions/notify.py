"""Email notifications about burning actions, honouring each user's preferences."""
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.emails import send_async_each
from .models import FireAction, Participation


def _wants(user, pref):
    prefs = getattr(user, 'preferences', None)
    return getattr(prefs, pref, True) if prefs else True


def _summary(action):
    when = action.scheduled_date.strftime('%d/%m/%Y') + (f' às {action.start_time:%H:%M}' if action.start_time else '')
    parcels = ', '.join(f'{p.name} ({p.concelho})' if p.concelho else p.name for p in action.parcels.all()) or '—'
    return (f'{action.get_action_type_display()}{" (ação de formação)" if action.training else ""}: {action.name}\n'
            f'Data: {when}\nParcelas: {parcels}')


def notify_new_action(request, action):
    url = request.build_absolute_uri(reverse('fire_actions:detail', args=[action.pk]))
    users = get_user_model().objects.filter(is_active=True).exclude(email='').exclude(pk=request.user.pk) \
        .select_related('preferences')
    send_async_each('[Fogo Bom] Nova ação anunciada: ' + action.name,
                    f'{_summary(action)}\n\nVeja os detalhes e inscreva-se em:\n{url}\n\n'
                    'Pode desativar estes avisos em "O meu perfil".',
                    [u.email for u in users if _wants(u, 'email_new_actions')])


def notify_action_update(request, action, what):
    url = request.build_absolute_uri(reverse('fire_actions:detail', args=[action.pk]))
    parts = action.participations.exclude(intent=Participation.INTENT_NAO).exclude(user=request.user) \
        .select_related('user', 'user__preferences')
    send_async_each(f'[Fogo Bom] {what}: {action.name}',
                    f'{what}.\n\n{_summary(action)}'
                    + (f'\nMotivo: {action.status_reason}' if action.status_reason else '') + f'\n\n{url}',
                    [p.user.email for p in parts if p.user.email and _wants(p.user, 'email_action_updates')])


def send_reminders(day, base_url=''):
    """Reminder for actions on `day` to participants who said they will go (or were confirmed)."""
    sent = 0
    for action in FireAction.objects.filter(scheduled_date=day, status__in=FireAction.OPEN_STATUSES) \
            .exclude(status=FireAction.STATUS_ADIADA):
        parts = action.participations.filter(intent=Participation.INTENT_VOU).exclude(confirmed=False) \
            .select_related('user', 'user__preferences')
        emails = [p.user.email for p in parts if p.user.email and _wants(p.user, 'email_reminders')]
        url = base_url.rstrip('/') + reverse('fire_actions:detail', args=[action.pk])
        meet = f'\nPonto de encontro: {action.meeting_notes}' if action.meeting_notes else ''
        send_async_each(f'[Fogo Bom] Lembrete: {action.name} amanhã',
                        f'{_summary(action)}{meet}\nEstado: {action.get_status_display()}\n\n{url}', emails)
        sent += len(emails)
    return sent
