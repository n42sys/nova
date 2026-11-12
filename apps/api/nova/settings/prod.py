"""Production settings. Every required value must come from the environment."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import NOVA_BASE_DOMAIN, REDIS_URL, env

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_CONTENT_TYPE_NOSNIFF = True

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_DOMAIN = f".{NOVA_BASE_DOMAIN}"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_DOMAIN = f".{NOVA_BASE_DOMAIN}"

# Shared cache so allauth rate limits (and later token throttles) hold across workers.
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
}

# Email goes out through Resend from a Celery task. Required in prod.
RESEND_API_KEY = env("RESEND_API_KEY")
NOVA_EMAIL_FROM = env("NOVA_EMAIL_FROM")
DEFAULT_FROM_EMAIL = NOVA_EMAIL_FROM
EMAIL_BACKEND = "core.email.ResendCeleryEmailBackend"

# Payment secrets are encrypted with these (newest first). Required in prod.
NOVA_FERNET_KEYS = env.list("NOVA_FERNET_KEYS")
if not NOVA_FERNET_KEYS:
    raise ImproperlyConfigured("NOVA_FERNET_KEYS must be set in production")
