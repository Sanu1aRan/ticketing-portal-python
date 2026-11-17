"""
Login, registration, password change and reset links.  (AuthService.java)
"""

import hashlib
import re
import secrets
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from ..models import User
from ..security import ServiceError, check_password, generate_token, hash_password
from . import email_service

MAX_ATTEMPTS = 5
LOCK_MILLIS = 15 * 60 * 1000
RESET_COOLDOWN_MILLIS = 2 * 60 * 1000
RESET_TOKEN_MINUTES = 30

EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")

# In-memory only: resets when the server restarts (same as Java).
_lock = threading.Lock()
_login_attempts = {}      # email -> {"count", "last_fail_at", "locked_until"}
_last_reset_request = {}  # email -> time of last "forgot password" request


def is_blank(value):
    return value is None or str(value).strip() == ""


def _now_millis():
    return int(time.time() * 1000)


def _sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_link_token():
    # 32 random bytes as URL-safe text (same as Java's Base64 url encoder)
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Login attempt limiting: 5 wrong passwords lock that email for 15 minutes
# ---------------------------------------------------------------------------
def _check_not_locked(key):
    with _lock:
        attempt = _login_attempts.get(key)
        if attempt is None:
            return
        now = _now_millis()
        if attempt["locked_until"] > now:
            mins = (attempt["locked_until"] - now) // 60000 + 1
            raise ServiceError(f"Too many failed attempts. Try again in {mins} minute(s).")
        if attempt["locked_until"] != 0:
            attempt["count"] = 0
            attempt["locked_until"] = 0


def _record_failure(key):
    with _lock:
        if len(_login_attempts) > 10000:
            _login_attempts.clear()  # memory guard
        attempt = _login_attempts.setdefault(
            key, {"count": 0, "last_fail_at": 0, "locked_until": 0}
        )
        now = _now_millis()
        if now - attempt["last_fail_at"] > LOCK_MILLIS:
            attempt["count"] = 0
        attempt["last_fail_at"] = now
        attempt["count"] += 1
        if attempt["count"] >= MAX_ATTEMPTS:
            attempt["locked_until"] = now + LOCK_MILLIS
            attempt["count"] = 0


def _clear_attempts(key):
    with _lock:
        _login_attempts.pop(key, None)


def reset_memory():
    """Forget all lockouts and cooldowns (used by the automated tests)."""
    with _lock:
        _login_attempts.clear()
        _last_reset_request.clear()


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------
def login(email, password):
    """Returns (token, user). Raises ServiceError when the login is refused."""
    key = "" if email is None else email.strip().lower()
    _check_not_locked(key)

    user = None if is_blank(email) else User.objects.filter(email=email.strip()).first()
    if user is None or is_blank(password) or not check_password(password, user.password):
        _record_failure(key)
        raise ServiceError("Invalid email or password")
    if not user.active:
        raise ServiceError("Your account has been deactivated. Please contact admin.")
    _clear_attempts(key)
    return generate_token(user.email), user


def register(full_name, email, password, company):
    if is_blank(full_name) or is_blank(email) or is_blank(password) or is_blank(company):
        raise ServiceError("All fields are required")
    email = email.strip()
    if not EMAIL_PATTERN.fullmatch(email):
        raise ServiceError("Invalid email address")
    if len(password) < 6:
        raise ServiceError("Password must be at least 6 characters")
    if len(full_name) > 100 or len(company) > 100 or len(email) > 150:
        raise ServiceError("Input is too long")
    if User.objects.filter(email=email).exists():
        raise ServiceError("Email already registered")

    User.objects.create(
        full_name=full_name.strip(),
        email=email,
        password=hash_password(password),
        company=company.strip(),
        role="client",
    )
    return "Account created successfully"


def change_password(user, current_password, new_password):
    if is_blank(current_password) or not check_password(current_password, user.password):
        raise ServiceError("Current password is incorrect")
    if new_password is None or len(new_password) < 6:
        raise ServiceError("New password must be at least 6 characters")
    if check_password(new_password, user.password):
        raise ServiceError("New password must be different from your current password")
    user.password = hash_password(new_password)
    user.reset_token_hash = None
    user.reset_token_expiry = None
    user.save()


def forgot_password(email):
    """Sends a one-time reset link. Behaves the same whether or not the email exists."""
    if is_blank(email):
        return

    key = email.strip().lower()
    now = _now_millis()
    with _lock:
        if len(_last_reset_request) > 10000:
            _last_reset_request.clear()  # memory guard
        last = _last_reset_request.get(key)
        if last is not None and now - last < RESET_COOLDOWN_MILLIS:
            return  # cooldown: at most one email every 2 minutes
        _last_reset_request[key] = now

    user = User.objects.filter(email=email.strip()).first()
    if user is None or not user.active:
        return

    token = _new_link_token()
    # Only the hash is stored, so a database leak does not expose usable links
    user.reset_token_hash = _sha256(token)
    user.reset_token_expiry = timezone.now() + timedelta(minutes=RESET_TOKEN_MINUTES)
    user.save()

    link = settings.FRONTEND_URL + "/reset-password?token=" + token
    email_service.send_email(
        user.email,
        "Password Reset — Sri Lanka Customs ICT Portal",
        "Dear " + user.full_name + ",\n\n"
        "We received a request to reset your password.\n\n"
        "Click the link below to choose a new password. "
        "The link works once and expires in " + str(RESET_TOKEN_MINUTES) + " minutes:\n\n"
        + link + "\n\n"
        "If you did not request this, ignore this email. Your password has not been changed.\n\n"
        "Sri Lanka Customs ICT Directorate",
    )


def reset_password(token, new_password):
    if is_blank(token):
        raise ServiceError("Invalid or expired reset link")
    if new_password is None or len(new_password) < 6:
        raise ServiceError("New password must be at least 6 characters")

    user = User.objects.filter(reset_token_hash=_sha256(token.strip())).first()
    if user is None:
        raise ServiceError("Invalid or expired reset link")
    if (
        user.reset_token_expiry is None
        or user.reset_token_expiry < timezone.now()
        or not user.active
    ):
        raise ServiceError("Invalid or expired reset link")
    if check_password(new_password, user.password):
        raise ServiceError("New password must be different from your current password")

    user.password = hash_password(new_password)
    user.reset_token_hash = None  # one-time use
    user.reset_token_expiry = None
    user.save()
    _clear_attempts(user.email.lower())


def send_password_link(user, subject, intro, valid_minutes):
    """
    Emails a one-time link to set a password. The account's current password
    is not touched until the user clicks the link.
    """
    token = _new_link_token()
    user.reset_token_hash = _sha256(token)
    user.reset_token_expiry = timezone.now() + timedelta(minutes=valid_minutes)
    user.save()

    if valid_minutes >= 120:
        valid_for = str(valid_minutes // 60) + " hours"
    else:
        valid_for = str(valid_minutes) + " minutes"

    link = settings.FRONTEND_URL + "/reset-password?token=" + token
    email_service.send_email(
        user.email,
        subject,
        "Dear " + user.full_name + ",\n\n"
        + intro + "\n\n"
        "Click the link below to set your password. "
        "The link works once and expires in " + valid_for + ":\n\n"
        + link + "\n\n"
        "Sri Lanka Customs ICT Directorate",
    )
