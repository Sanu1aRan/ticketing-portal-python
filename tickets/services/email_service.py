"""
Sends emails.  (EmailService.java)

Java marked sendEmail with @Async: the email goes out in the background, so
the user never waits for the mail server, and a mail problem never breaks
the action they just did. A background thread does the same job here.
"""

import logging
import threading

from django.conf import settings
from django.core.mail import send_mail

log = logging.getLogger(__name__)


def _send(to, subject, body):
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to], fail_silently=False)
    except Exception:
        log.exception("Failed to send email to %s (%s)", to, subject)


def send_email(to, subject, body):
    if not to:
        return
    if settings.EMAIL_ASYNC:
        threading.Thread(target=_send, args=(to, subject, body), daemon=True).start()
    else:
        _send(to, subject, body)
