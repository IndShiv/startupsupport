"""Django settings for the BUSS Startup Support app.

All deployment-specific values come from environment variables; see
`.env.example` and the README for the full list.
"""

import os
from pathlib import Path

import dj_database_url
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-insecure-secret-key"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "auditlog",
    "siteconfig",
    "crm",
    "public",
    "staff",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
]

ROOT_URLCONF = "buss.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "siteconfig.context_processors.public_page",
                "staff.context_processors.staff_nav",
            ],
        },
    },
]

WSGI_APPLICATION = "buss.wsgi.application"

# SQLite locally, PostgreSQL in production: DATABASE_URL=postgres://user:pass@host:5432/buss
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalisation: English UI, Dutch prepared.
LANGUAGE_CODE = "en"
LANGUAGES = [("en", _("English")), ("nl", _("Dutch"))]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Amsterdam"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.environ.get("DJANGO_MEDIA_ROOT", BASE_DIR / "media"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# Shared cache (database table) so the form's rate limit works across worker processes.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "buss_cache"}}
# Set to 1 only when running behind a reverse proxy that sets X-Forwarded-For.
TRUST_X_FORWARDED_FOR = env_bool("DJANGO_TRUST_X_FORWARDED_FOR", False)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "staff:login"
LOGIN_REDIRECT_URL = "staff:home"
LOGOUT_REDIRECT_URL = "staff:login"

# Absolute address of the app, used for links in emails.
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000").rstrip("/")

# Email. EMAIL_PROVIDER picks the sender: console (prints to the log), smtp, or graph (Microsoft Graph).
EMAIL_PROVIDER = os.environ.get("EMAIL_PROVIDER", "console").lower()
EMAIL_BACKEND = {
    "console": "django.core.mail.backends.console.EmailBackend",
    "smtp": "django.core.mail.backends.smtp.EmailBackend",
    "graph": "buss.mail_graph.GraphEmailBackend",
}.get(EMAIL_PROVIDER, EMAIL_PROVIDER)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "BUSS Startup Support <startupsupport@buas.nl>")
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO", "startupsupport@buas.nl")
EMAIL_TIMEOUT = 20
# SMTP
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
# Microsoft Graph (app registration with the Mail.Send application permission)
GRAPH_TENANT_ID = os.environ.get("GRAPH_TENANT_ID", "")
GRAPH_CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID", "")
GRAPH_CLIENT_SECRET = os.environ.get("GRAPH_CLIENT_SECRET", "")
GRAPH_SENDER = os.environ.get("GRAPH_SENDER", "startupsupport@buas.nl")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"crm": {"handlers": ["console"], "level": "INFO"}, "buss": {"handlers": ["console"], "level": "INFO"}},
}

# Production hardening (only active when DEBUG is off).
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"

# Audit log: models are registered explicitly (see crm/models.py, siteconfig/models.py).
AUDITLOG_INCLUDE_ALL_MODELS = False
