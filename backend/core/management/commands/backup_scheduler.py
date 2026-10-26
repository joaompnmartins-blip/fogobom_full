"""
Long-running loop for daily tasks, started in the background by the
container's start command:
  - backup (database every day, media on Sundays), if BACKUP_S3_* is set;
  - reminders for tomorrow's burning actions.
"""
import os
import time
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from .backup import backup_config


def next_run(now, hour):
    """Next local datetime at `hour`:00 strictly after `now`."""
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def run_daily_tasks(target, stdout=None, stderr=None):
    if backup_config():
        try:
            call_command('backup', media=target.weekday() == 6)
        except Exception as exc:  # already reported by email
            if stderr:
                stderr.write(f'Backup: {exc}')
    try:
        from fire_actions.notify import send_reminders
        n = send_reminders(target.date() + timedelta(days=1), settings.SITE_URL)
        if stdout:
            stdout.write(f'Lembretes de ações enviados: {n}')
    except Exception as exc:
        if stderr:
            stderr.write(f'Lembretes: {exc}')


class Command(BaseCommand):
    help = 'Run daily tasks: backups (if configured) and action reminders.'

    def handle(self, *args, **opts):
        hour = int(os.environ.get('BACKUP_HOUR', '3'))
        while True:
            now = timezone.localtime()
            target = next_run(now, hour)
            self.stdout.write(f'Tarefas diárias: próxima execução em {target:%Y-%m-%d %H:%M}')
            time.sleep(max(1, (target - now).total_seconds()))
            run_daily_tasks(target, self.stdout, self.stderr)
