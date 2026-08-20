import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SECRET_KEY")

DEBUG = os.getenv("DEBUG", "False") == "True"

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "app",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


ROOT_URLCONF = "Finch.urls"

LOGIN_URL = "/login/"

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
            ],
        },
    },
]

WSGI_APPLICATION = "Finch.wsgi.application"


DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv("DATABASE_URL"),
        conn_max_age=600,
    )
}

if not os.getenv("DATABASE_URL"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME"),
            "USER": os.getenv("DB_USER"),
            "PASSWORD": os.getenv("DB_PASSWORD"),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


STATIC_URL = "/static/"

STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATICFILES_STORAGE = (
    "whitenoise.storage.CompressedManifestStaticFilesStorage"
)


MEDIA_URL = "/media/"

MEDIA_ROOT = BASE_DIR / "media"


# if os.getenv("RENDER"):
#     EMAIL_BACKEND = (
#         "django.core.mail.backends.console.EmailBackend"
#     )
# else:
#     EMAIL_BACKEND = (
#         "django.core.mail.backends.smtp.EmailBackend"
#     )

#     EMAIL_HOST = "smtp.zoho.in"
#     EMAIL_PORT = 587
#     EMAIL_USE_TLS = True
#     EMAIL_USE_SSL = False

#     EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
#     EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")

#     DEFAULT_FROM_EMAIL = os.getenv(
#         "DEFAULT_FROM_EMAIL",
#         EMAIL_HOST_USER,
#     )

# EMAIL_TIMEOUT = 30

# BYPASS_PASSWORD = os.getenv("BYPASS_PASSWORD")

# SESSION_COOKIE_AGE = 3600

# SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Resend
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL")

DEFAULT_FROM_EMAIL = RESEND_FROM_EMAIL

EMAIL_TIMEOUT = 30

BYPASS_PASSWORD = os.getenv("BYPASS_PASSWORD")

SESSION_COOKIE_AGE = 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = True


if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True


GROQ_API_KEY = os.getenv("GROQ_API_KEY")

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-120b",
)


CELERY_BROKER_URL = os.getenv(
    "REDIS_URL",
    "redis://localhost:6379/0",
)

CELERY_RESULT_BACKEND = os.getenv(
    "REDIS_URL",
    "redis://localhost:6379/0",
)

CELERY_TIMEZONE = TIME_ZONE

CELERY_TASK_TRACK_STARTED = True

CELERY_TASK_TIME_LIMIT = 30 * 60


CACHES = {
    "default": {
        "BACKEND": (
            "django.core.cache.backends.redis.RedisCache"
        ),
        "LOCATION": os.getenv(
            "REDIS_URL",
            "redis://localhost:6379/1",
        ),
    },
}

TRUSTED_DEVICE_COOKIE = "finch_trusted_device"
TRUSTED_DEVICE_MAX_AGE = 60 * 60 * 24 * 30