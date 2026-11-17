"""
Security: login tokens (JWT), password hashing (BCrypt) and the "who is
calling?" check that runs before every protected endpoint.

Java files this replaces: JwtUtil.java, JwtAuthFilter.java and the
PasswordEncoder bean from SecurityConfig.java.
"""

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication
from rest_framework.response import Response

from .models import User

log = logging.getLogger(__name__)


class ServiceError(Exception):
    """
    A normal "you cannot do that" error, e.g. "Ticket not found".
    Java threw RuntimeException and every controller turned it into
    400 {"message": "..."}. Here exception_handler() below does that once.
    """

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# JWT  (JwtUtil.java)
# ---------------------------------------------------------------------------
def generate_token(email):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": email,
        "iat": now,
        "exp": now + timedelta(hours=settings.JWT_EXPIRATION_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")


def extract_email(token):
    """Returns the email inside the token. Raises if the token is fake or expired."""
    payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    return payload.get("sub")


# ---------------------------------------------------------------------------
# Passwords  (BCryptPasswordEncoder)
# Same BCrypt format as Java, so hashes made by either system work in both.
# ---------------------------------------------------------------------------
def hash_password(raw_password):
    raw = raw_password.encode("utf-8")
    if len(raw) > 72:
        raise ServiceError("Password cannot be more than 72 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=10)).decode("ascii")


def check_password(raw_password, hashed):
    if not raw_password or not hashed:
        return False
    try:
        return bcrypt.checkpw(raw_password.encode("utf-8")[:72], hashed.encode("ascii"))
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Token check on every request  (JwtAuthFilter.java)
# ---------------------------------------------------------------------------
class JwtAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION")
        if not header or not header.startswith("Bearer "):
            return None  # no token -> treated as "not logged in" (403)

        token = header.replace("Bearer ", "")
        try:
            email = extract_email(token)
        except Exception:
            raise exceptions.AuthenticationFailed("Invalid token")
        if email is None:
            return None

        user = User.objects.filter(email=email).first()
        if user is None or not user.active:
            raise exceptions.AuthenticationFailed("Account deactivated or not found")
        return (user, token)


# ---------------------------------------------------------------------------
# One place that turns every error into the JSON shape React expects:
#     {"message": "..."}
# ---------------------------------------------------------------------------
def exception_handler(exc, context):
    if isinstance(exc, ServiceError):
        return Response({"message": exc.message}, status=exc.status)

    # Token was sent but is wrong / user deactivated -> 401, like JwtAuthFilter
    if isinstance(exc, exceptions.AuthenticationFailed):
        return Response({"message": str(exc.detail)}, status=401)

    # No token at all -> 403 with an empty body, like Spring Security
    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.PermissionDenied)):
        return Response(status=403)

    if isinstance(exc, exceptions.APIException):
        return Response({"message": str(exc.detail)}, status=exc.status_code)

    log.exception("Unexpected error in %s", context.get("view"))
    return Response({"message": "Internal server error"}, status=500)
