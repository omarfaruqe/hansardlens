"""Django settings for HansardLens. All environment-specific values come from env vars."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config import __version__

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(int(default))).lower() in {"1", "true", "yes"}


def env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEV_SECRET_KEY = "dev-only-insecure-key"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", DEV_SECRET_KEY)
DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

if env_bool("DJANGO_PRODUCTION") and SECRET_KEY in {DEV_SECRET_KEY, "change-me", ""}:
    raise ImproperlyConfigured("Set DJANGO_SECRET_KEY to a long random value in production.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django.contrib.humanize",
    "rest_framework",
    "drf_spectacular",
    "debates",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "debates.middleware.LanguageParameterMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# PostgreSQL only: search relies on its full-text features.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "hansardlens"),
        "USER": os.environ.get("POSTGRES_USER", "hansardlens"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(os.environ.get("POSTGRES_CONN_MAX_AGE", "60")),
    }
}

# Analysis results and API throttling. A file cache is shared by every process (web
# workers and management commands); tests and quick checks use memory.
if os.environ.get("HANSARD_CACHE", "memory") == "file":
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": str(DATA_DIR / "cache"),
            "OPTIONS": {"MAX_ENTRIES": 5000},
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("fr", "Français")]
LOCALE_PATHS = [BASE_DIR / "locale"]
LANGUAGE_COOKIE_NAME = "hansardlens_language"
LANGUAGE_COOKIE_AGE = 365 * 24 * 3600
LANGUAGE_COOKIE_SAMESITE = "Lax"
TIME_ZONE = "America/Toronto"
USE_I18N = True
USE_TZ = True

# Optional URL prefix when served behind a reverse proxy under a sub-path, e.g.
# DJANGO_SCRIPT_NAME=/hansardlens. The proxy strips the prefix before
# forwarding; Django adds it back to every link, static URL and cookie path.
SCRIPT_NAME = os.environ.get("DJANGO_SCRIPT_NAME", "").rstrip("/")
FORCE_SCRIPT_NAME = SCRIPT_NAME or None
COOKIE_PATH = f"{SCRIPT_NAME}/" if SCRIPT_NAME else "/"
SESSION_COOKIE_PATH = CSRF_COOKIE_PATH = LANGUAGE_COOKIE_PATH = COOKIE_PATH
# Distinct names, so another Django app on the same host never shares these cookies.
SESSION_COOKIE_NAME = "hansardlens_sessionid"
CSRF_COOKIE_NAME = "hansardlens_csrftoken"

# Absolute when prefixed: gunicorn starts Django without setting the script prefix, so a
# relative STATIC_URL would be cached unprefixed. WhiteNoise strips FORCE_SCRIPT_NAME
# from it again when matching incoming (already stripped) paths.
STATIC_URL = f"{SCRIPT_NAME}/static/" if SCRIPT_NAME else "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # Hashed, compressed files in production (needs collectstatic); plain files otherwise.
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if env_bool("DJANGO_STATIC_MANIFEST")
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Security headers. HTTPS-only cookies and redirects are switched on with
# DJANGO_HTTPS=1 once the site is served over HTTPS.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if env_bool("DJANGO_HTTPS"):
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    LANGUAGE_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", default=True)
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "3600"))
if env_bool("DJANGO_BEHIND_PROXY"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}

# REST API: read-only, anonymous, rate-limited.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": os.environ.get("API_RATE", "120/minute")},
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "HansardLens API",
    "DESCRIPTION": (
        "Read-only access to House of Commons of Canada debates in English and French: "
        "sittings, speeches, bilingual search, term trends, language on the floor, topics "
        "and term shifts. Debate text is Parliament's copyright."
    ),
    "VERSION": __version__,
    "SERVE_INCLUDE_SCHEMA": False,
}

# Polite identification for requests to ourcommons.ca
HANSARD_USER_AGENT = os.environ.get(
    "HANSARD_USER_AGENT", f"HansardLens/{__version__} (open-source portfolio project)"
)

# Committees whose public meetings are loaded (acronyms as used by the House).
HANSARD_COMMITTEES = [
    c.strip().upper()
    for c in os.environ.get("HANSARD_COMMITTEES", "FINA,OGGO,ETHI").split(",")
    if c.strip()
]
