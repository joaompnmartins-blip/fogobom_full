"""Daily email digest of deadlines: a notice 15 days before, a last reminder 3 days before and a note when
overdue. Each stage of each deadline is emailed once per user."""
from collections import defaultdict

from django.contrib.auth import get_user_model

from core.emails import send_async_each
from .deadlines import all_deadlines
from .models import AlertLog

NOTICE_DAYS, LAST_DAYS = 15, 3


def _stage(item):
    if item['days'] < 0:
        return 'atraso'
    if item['days'] <= LAST_DAYS:
        return 'ultimo'
    if item['days'] <= NOTICE_DAYS:
        return 'aviso'
    return None


def send_deadline_alerts(today=None, base_url=''):
    """Returns the number of emails sent."""
    pending = defaultdict(list)
    for item in all_deadlines(today):
        stage = _stage(item)
        if not stage:
            continue
        for uid in item['users']:
            pending[uid].append((f'{item["key"]}:{stage}', stage, item))
    if not pending:
        return 0
    users = get_user_model().objects.filter(pk__in=pending, is_active=True).exclude(email='') \
        .select_related('preferences')
    sent = 0
    for user in users:
        prefs = getattr(user, 'preferences', None)
        if prefs is not None and not prefs.email_deadlines:
            continue
        done = set(AlertLog.objects.filter(user=user, key__in=[k for k, _, _ in pending[user.pk]])
                   .values_list('key', flat=True))
        new = [(k, s, i) for k, s, i in pending[user.pk] if k not in done]
        if not new:
            continue
        lines = []
        for _, stage, i in new:
            when = (f'em atraso desde {i["due"]:%d/%m/%Y}' if stage == 'atraso'
                    else f'até {i["due"]:%d/%m/%Y} ({i["days"]} dia{"s" if i["days"] != 1 else ""})')
            lines.append(f'• {i["kind_label"]}: {i["title"]} — {when}\n  {i["detail"]}\n  {base_url.rstrip("/")}{i["url"]}')
        overdue = sum(1 for _, s, _ in new if s == 'atraso')
        subject = '[Fogo Bom] Prazos' + (f': {overdue} em atraso' if overdue else ' a aproximar-se')
        send_async_each(subject, 'Prazos que requerem a sua atenção:\n\n' + '\n\n'.join(lines)
                        + f'\n\nTodos os prazos: {base_url.rstrip("/")}/prazos/\n'
                        'Pode desativar estes avisos em "O meu perfil".', [user.email])
        AlertLog.objects.bulk_create([AlertLog(user=user, key=k[:200]) for k, _, _ in new], ignore_conflicts=True)
        sent += 1
    return sent
