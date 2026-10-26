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


def _send_each(subject, message, recipients):
    for email in recipients:
        _send_mail_logged(subject, message, [email])


def send_async_each(subject, message, recipients):
    """One email per recipient (addresses are not disclosed to each other), in one background thread."""
    recipients = sorted(set(r for r in recipients if r))
    if recipients:
        threading.Thread(target=_send_each, args=(subject, message, recipients), daemon=True).start()
