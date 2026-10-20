import logging
import threading

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _send_mail_logged(subject, message, recipient_list):
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipient_list)
    except Exception:
        logger.exception('Falha ao enviar email "%s" para %s', subject, recipient_list)


def send_async(subject, message, recipient_list):
    """Send a plain-text email in a background thread so requests aren't blocked by SMTP."""
    threading.Thread(
        target=_send_mail_logged,
        args=(subject, message, recipient_list),
        daemon=True,
    ).start()
