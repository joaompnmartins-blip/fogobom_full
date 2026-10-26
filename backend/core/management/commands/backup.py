"""
Back up the database (pg_dump) and, optionally, uploaded media to S3-compatible
storage (Cloudflare R2). Configured with BACKUP_S3_* env vars; does nothing
when they are missing, so it is safe to run on every start.
"""
import os
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

DB_PREFIX = 'db/'
MEDIA_PREFIX = 'media/'


def backup_config():
    cfg = {
        'bucket':     os.environ.get('BACKUP_S3_BUCKET', ''),
        'endpoint':   os.environ.get('BACKUP_S3_ENDPOINT_URL', ''),
        'access_key': os.environ.get('BACKUP_S3_ACCESS_KEY_ID', ''),
        'secret_key': os.environ.get('BACKUP_S3_SECRET_ACCESS_KEY', ''),
        'region':     os.environ.get('BACKUP_S3_REGION', 'auto'),
    }
    return cfg if all(cfg[k] for k in ('bucket', 'endpoint', 'access_key', 'secret_key')) else None


def s3_client(cfg):
    import boto3
    return boto3.client('s3', endpoint_url=cfg['endpoint'], region_name=cfg['region'],
                        aws_access_key_id=cfg['access_key'], aws_secret_access_key=cfg['secret_key'])


def prune(client, bucket, prefix, keep):
    """Delete all but the `keep` newest objects under `prefix` (keys sort by timestamp)."""
    keys = []
    for page in client.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
        keys += [o['Key'] for o in page.get('Contents', [])]
    old = sorted(keys)[:-keep] if keep > 0 else []
    if old:
        client.delete_objects(Bucket=bucket, Delete={'Objects': [{'Key': k} for k in old]})
    return old


class Command(BaseCommand):
    help = 'Back up the database (and optionally media) to S3-compatible storage.'

    def add_arguments(self, parser):
        parser.add_argument('--media', action='store_true', help='Also back up uploaded media files.')
        parser.add_argument('--keep-db', type=int, default=30)
        parser.add_argument('--keep-media', type=int, default=4)
        parser.add_argument('--output-dir', help='Write the files here instead of uploading (manual use/testing).')

    def handle(self, *args, **opts):
        cfg = backup_config()
        if not cfg and not opts['output_dir']:
            self.stdout.write('Backup: BACKUP_S3_* não configurado, a ignorar.')
            return
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        try:
            with tempfile.TemporaryDirectory() as tmp:
                files = [(DB_PREFIX, self.dump_database(Path(tmp) / f'fogobom-{stamp}.dump'))]
                if opts['media']:
                    media = self.archive_media(Path(tmp) / f'fogobom-media-{stamp}.tar.gz')
                    if media:
                        files.append((MEDIA_PREFIX, media))
                if opts['output_dir']:
                    out = Path(opts['output_dir'])
                    out.mkdir(parents=True, exist_ok=True)
                    for _, f in files:
                        f.replace(out / f.name)
                        self.stdout.write(f'Backup: {out / f.name} ({(out / f.name).stat().st_size} bytes)')
                    return
                client = s3_client(cfg)
                for prefix, f in files:
                    client.upload_file(str(f), cfg['bucket'], prefix + f.name)
                    self.stdout.write(f'Backup: enviado {prefix}{f.name} ({f.stat().st_size} bytes)')
                removed = prune(client, cfg['bucket'], DB_PREFIX, opts['keep_db'])
                if opts['media']:
                    removed += prune(client, cfg['bucket'], MEDIA_PREFIX, opts['keep_media'])
                if removed:
                    self.stdout.write(f'Backup: removidos {len(removed)} backups antigos')
        except Exception as exc:
            self.notify_failure(exc)
            raise CommandError(f'Backup falhou: {exc}') from exc

    def dump_database(self, path):
        db = settings.DATABASES['default']
        env = {**os.environ, 'PGPASSWORD': db['PASSWORD']}
        cmd = ['pg_dump', '--format=custom', '--no-owner', '--host', db['HOST'], '--port', str(db['PORT']),
               '--username', db['USER'], '--file', str(path), db['NAME']]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f'pg_dump: {result.stderr.strip()[:500]}')
        return path

    def archive_media(self, path):
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.exists() or not any(p.is_file() for p in media_root.rglob('*')):
            self.stdout.write('Backup: sem ficheiros de media.')
            return None
        with tarfile.open(path, 'w:gz') as tar:
            tar.add(media_root, arcname='media',
                    filter=lambda ti: None if 'lost+found' in ti.name else ti)
        return path

    def notify_failure(self, exc):
        if not settings.ADMIN_EMAIL:
            return
        try:
            send_mail('[Fogo Bom] Falha no backup', f'O backup automático falhou:\n\n{exc}',
                      settings.DEFAULT_FROM_EMAIL, [settings.ADMIN_EMAIL])
        except Exception:
            pass
