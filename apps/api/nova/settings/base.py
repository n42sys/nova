"""Settings shared by every environment. All values are read from the environment."""

from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "allauth",
    "allauth.account",
    "allauth.headless",
    "core",
    "payments",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "nova.urls"

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

WSGI_APPLICATION = "nova.wsgi.application"
ASGI_APPLICATION = "nova.asgi.application"

DATABASES = {"default": env.db("DATABASE_URL")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "core.User"
AUTHENTICATION_BACKENDS = ["allauth.account.auth_backends.AuthenticationBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Nova
NOVA_BASE_DOMAIN = env("NOVA_BASE_DOMAIN")
NOVA_ADMIN_URL = env("NOVA_ADMIN_URL")
NOVA_FERNET_KEYS = env.list("NOVA_FERNET_KEYS", default=[])
# Number of reverse proxies (e.g. Caddy) in front of the API; used to read the client IP
# from X-Forwarded-For. 0 means trust REMOTE_ADDR only.
NOVA_TRUSTED_PROXY_COUNT = env.int("NOVA_TRUSTED_PROXY_COUNT", default=0)
# Requests per API token (DRF rate syntax), keyed by token prefix.
NOVA_API_TOKEN_RATE = env("NOVA_API_TOKEN_RATE", default="600/min")

# Email
RESEND_API_KEY = env("RESEND_API_KEY", default="")
NOVA_EMAIL_FROM = env("NOVA_EMAIL_FROM", default="")
DEFAULT_FROM_EMAIL = NOVA_EMAIL_FROM
# Overridden per environment: console (dev), locmem (test), Resend via Celery (prod).
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Media storage (Cloudflare R2)
R2_ACCOUNT_ID = env("R2_ACCOUNT_ID", default="")
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
R2_BUCKET = env("R2_BUCKET", default="")
R2_PUBLIC_URL = env("R2_PUBLIC_URL", default="")
R2_ENDPOINT_URL = (
    env(
        "R2_ENDPOINT_URL",
        default=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else "",
    )
    or None
)
R2_REGION = "auto"

# Payments
PAYSTACK_API_BASE_URL = env("PAYSTACK_API_BASE_URL", default="https://api.paystack.co")
# Largest accepted upload, in bytes.
NOVA_MEDIA_MAX_BYTES = env.int("NOVA_MEDIA_MAX_BYTES", default=25 * 1024 * 1024)

# Redis / Celery
REDIS_URL = env("REDIS_URL")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = "UTC"
CELERY_TASK_ACKS_LATE = True
# Static schedule; run `celery -A nova beat` alongside the worker.
CELERY_BEAT_SCHEDULE = {
    "purge-stale-media-uploads": {
        "task": "core.tasks.purge_stale_uploads",
        "schedule": crontab(hour=3, minute=0),
    },
}

# Sessions, CSRF, CORS. The admin app and API share a parent domain (cookie domain set in
# prod). The CSRF cookie stays readable by JS so the admin app can send X-CSRFToken.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CORS_ALLOW_CREDENTIALS = True

# Auth (django-allauth, headless only, browser sessions only)
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
ACCOUNT_ADAPTER = "core.auth_adapter.AccountAdapter"
HEADLESS_ONLY = True
HEADLESS_CLIENTS = ("browser",)
HEADLESS_FRONTEND_URLS = {
    "account_confirm_email": f"{NOVA_ADMIN_URL}/account/verify-email/{{key}}",
    "account_reset_password": f"{NOVA_ADMIN_URL}/account/password/reset",
    "account_reset_password_from_key": f"{NOVA_ADMIN_URL}/account/password/reset/key/{{key}}",
    "account_signup": f"{NOVA_ADMIN_URL}/account/signup",
}

# API
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": ["core.auth.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "core.exceptions.exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Nova API",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Stable component names for choice sets shared by several fields.
    "ENUM_NAME_OVERRIDES": {
        "RoleEnum": "core.models.Role",
        "SiteRoleEnum": "core.models.SITE_ROLE_CHOICES",
        "OrganizationStatusEnum": "core.models.Organization.Status",
        "SiteStatusEnum": "core.models.Site.Status",
        "InvitationStatusEnum": "core.models.Invitation.Status",
        "ApiTokenKindEnum": "core.models.ApiToken.Kind",
        "MediaStatusEnum": "core.models.MediaAsset.Status",
        "PaymentProviderEnum": "payments.models.PaymentAccount.Provider",
        "PaymentAccountStatusEnum": "payments.models.PaymentAccount.Status",
    },
}
