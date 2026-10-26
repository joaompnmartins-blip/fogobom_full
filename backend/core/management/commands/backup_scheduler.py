"""
Long-running loop that calls `backup` once a day (media on Sundays).
Started in the background by the container's start command.
"""
import os
import time
from datetime import datetime, timedelta

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from .backup import backup_config


def next_run(now, hour):
    """Next local datetime at `hour`:00 strictly after `now`."""
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


class Command(BaseCommand):
    help = 'Run daily backups (database every day, media on Sundays).'

    def handle(self, *args, **opts):
        if not backup_config():
            self.stdout.write('Backup scheduler: BACKUP_S3_* não configurado, a terminar.')
            return
        hour = int(os.environ.get('BACKUP_HOUR', '3'))
        while True:
            now = timezone.localtime()
            target = next_run(now, hour)
            self.stdout.write(f'Backup scheduler: próximo backup em {target:%Y-%m-%d %H:%M}')
            time.sleep(max(1, (target - now).total_seconds()))
            try:
                call_command('backup', media=target.weekday() == 6)
            except Exception as exc:  # already reported by email; keep the loop alive
                self.stderr.write(f'Backup scheduler: {exc}')
