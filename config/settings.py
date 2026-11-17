"""
Settings for the ICT Help Desk Ticketing System (Python version).

This file is the Python side of Java's application.properties + SecurityConfig.
Anything secret or different per machine (database password, JWT secret,
mail account) lives in config/local_settings.py, which is NOT pushed to GitHub.
Copy config/local_settings.example.py to config/local_settings.py to start.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Read values from config/local_settings.py (falls back to safe dev defaults)
# ---------------------------------------------------------------------------
try:
    from . import local_settings as _local
except ImportError:  # no local_settings.py yet
    _local = None


def cfg(name, default):
    return getattr(_local, name, default)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
DEBUG = cfg("DEBUG", True)
ALLOWED_HOSTS = cfg("ALLOWED_HOSTS", ["*"])

# Same job as jwt.secret in application.properties: signs the login tokens.
JWT_SECRET = cfg("JWT_SECRET", "dev-only-secret-change-me-before-production-0123456789")
# Java: EXPIRATION_TIME = 7 days. Production checklist says 8 hours.
JWT_EXPIRATION_HOURS = cfg("JWT_EXPIRATION_HOURS", 7 * 24)

if not DEBUG and (JWT_SECRET.startswith("dev-only-secret") or JWT_SECRET.startswith("change-this")):
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "Set your own JWT_SECRET in config/local_settings.py before running with DEBUG = False. "
        "Anyone who knows the secret can create login tokens."
    )

# Django needs its own key too (we do not use sessions, so it is rarely used).
SECRET_KEY = cfg("SECRET_KEY", JWT_SECRET)

# Java: app.frontend-url — used to build the links in reset / welcome emails.
FRONTEND_URL = cfg("FRONTEND_URL", "http://localhost:5173")

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "tickets",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
APPEND_SLASH = False  # React calls /api/tickets, not /api/tickets/
TEMPLATES = []

# ---------------------------------------------------------------------------
# Database  (Java: spring.datasource.*)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "config.mysql_backend",  # normal Django MySQL + XAMPP support
        "NAME": cfg("DB_NAME", "customs_ticketing_py"),
        "USER": cfg("DB_USER", "root"),
        "PASSWORD": cfg("DB_PASSWORD", ""),
        "HOST": cfg("DB_HOST", "localhost"),
        "PORT": cfg("DB_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            # Reject bad data instead of silently cutting it (XAMPP does not do this by default)
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}
if cfg("DATABASES", None):  # full override, e.g. another database engine
    DATABASES = cfg("DATABASES", None)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Java stored LocalDateTime.now() = the server's local clock, with no time zone.
# USE_TZ = False makes Django store and return times the same way.
TIME_ZONE = cfg("TIME_ZONE", "Asia/Colombo")
USE_TZ = False
USE_I18N = False

# ---------------------------------------------------------------------------
# CORS  (Java: SecurityConfig.corsConfigurationSource)
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = cfg(
    "CORS_ALLOWED_ORIGINS",
    ["http://localhost:5173", "http://localhost:3000"],
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]

# ---------------------------------------------------------------------------
# REST framework  (Java: SecurityConfig.filterChain + JwtAuthFilter)
# Every endpoint needs a valid token unless the view says it is public.
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["tickets.security.JwtAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "EXCEPTION_HANDLER": "tickets.security.exception_handler",
    "UNAUTHENTICATED_USER": None,
}

# ---------------------------------------------------------------------------
# File uploads  (Java: uploads/ folder next to the app, 10MB limit)
# ---------------------------------------------------------------------------
UPLOAD_DIR = Path(cfg("UPLOAD_DIR", BASE_DIR / "uploads"))
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# ---------------------------------------------------------------------------
# Email  (Java: spring.mail.*)
# With no mail account configured, emails are printed in the terminal instead
# of being sent, so the system still runs on a fresh machine.
# ---------------------------------------------------------------------------
EMAIL_HOST = cfg("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = cfg("EMAIL_PORT", 587)
EMAIL_HOST_USER = cfg("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = cfg("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = cfg("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = 30
DEFAULT_FROM_EMAIL = cfg("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "ict-portal@localhost")
EMAIL_BACKEND = cfg(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST_USER
    else "django.core.mail.backends.console.EmailBackend",
)
# Java used @Async, so a slow mail server never slows down the user.
EMAIL_ASYNC = cfg("EMAIL_ASYNC", True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    # 400-type answers ("wrong password", "not allowed") are normal; only log real errors
    "loggers": {"django.request": {"level": "ERROR"}},
}
