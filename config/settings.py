from datetime import timedelta
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file():
    path = BASE_DIR / ".env"
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file()

SECRET_KEY = os.environ.get("SECRET_KEY", "local-dev-only-change-before-production-pahle-app")
DEBUG = os.environ.get("DEBUG", "True").lower() in ("1", "true", "yes")

allowed = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,0.0.0.0")
ALLOWED_HOSTS = [h.strip() for h in allowed.split(",") if h.strip()]
render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if render_host and render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_host)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "maintenance",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "maintenance.api_cache.ApiGetCacheMiddleware",
]

ROOT_URLCONF = "config.urls"
AUTH_USER_MODEL = "maintenance.User"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

_sqlite = {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": BASE_DIR / "db.sqlite3",
}
_database_url = os.environ.get("DATABASE_URL", "").strip()
if _database_url:
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            _database_url,
            conn_max_age=0,
            conn_health_checks=True,
            ssl_require=True,
        )
    }
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
else:
    DATABASES = {"default": _sqlite}

# Per-user API GET cache. LocMem is enough for a single Gunicorn worker on Render.
# Set REDIS_URL later if you add Redis; until then do not use the DB as a cache.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pahle-api",
        "TIMEOUT": int(os.environ.get("API_CACHE_SECONDS", "60")),
        "OPTIONS": {"MAX_ENTRIES": 800},
    }
}
API_CACHE_SECONDS = int(os.environ.get("API_CACHE_SECONDS", "60"))

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedStaticFilesStorage"
            if not DEBUG
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

cors_default = "http://localhost:3000,http://127.0.0.1:3000,https://pahleapp-frontend.vercel.app"
env_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ALLOWED_ORIGINS", cors_default).split(",")
    if origin.strip()
]
# Always keep local + production frontend origins, even if Render env replaces the default.
CORS_ALLOWED_ORIGINS = list(dict.fromkeys(env_origins + cors_default.split(",")))
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://.*\.vercel\.app$",
]
CORS_ALLOW_CREDENTIALS = True
CORS_PREFLIGHT_MAX_AGE = 86400
CSRF_TRUSTED_ORIGINS = list(CORS_ALLOWED_ORIGINS)
if render_host:
    CSRF_TRUSTED_ORIGINS.append(f"https://{render_host}")
CSRF_TRUSTED_ORIGINS.append("https://*.vercel.app")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://pahleapp-frontend.vercel.app")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.resend.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "465"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "resend")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "true").lower() in ("1", "true", "yes")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "false").lower() in ("1", "true", "yes")
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "8"))
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "PAHLE-APP <noreply@pahle-app.in>")
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST_PASSWORD
    else "django.core.mail.backends.console.EmailBackend"
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "loggers": {
        "maintenance.notifications": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
    },
}
