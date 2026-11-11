"""Test settings used by pytest."""

import os

os.environ.setdefault("SECRET_KEY", "django-insecure-test-only")
os.environ.setdefault("DATABASE_URL", "postgres://nova:nova@localhost:55432/nova")
os.environ.setdefault("REDIS_URL", "redis://localhost:56379/0")
os.environ.setdefault("NOVA_BASE_DOMAIN", "nova.test")
os.environ.setdefault("NOVA_ADMIN_URL", "http://admin.nova.test")
os.environ.setdefault("ALLOWED_HOSTS", "testserver,localhost")
os.environ.setdefault("NOVA_EMAIL_FROM", "Nova <nova@nova.test>")
os.environ.setdefault("CSRF_TRUSTED_ORIGINS", "http://admin.nova.test")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://admin.nova.test")

from .base import *  # noqa: E402, F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

INSTALLED_APPS = [*INSTALLED_APPS, "core.tests.tenant_testapp"]  # noqa: F405
