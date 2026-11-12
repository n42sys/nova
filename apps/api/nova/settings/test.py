"""Test settings used by pytest."""

import os

os.environ.setdefault("SECRET_KEY", "django-insecure-test-only")
os.environ.setdefault("DATABASE_URL", "postgres://nova:nova@localhost:55432/nova")
os.environ.setdefault("REDIS_URL", "redis://localhost:56379/0")
os.environ.setdefault("NOVA_BASE_DOMAIN", "nova.test")
os.environ.setdefault("NOVA_ADMIN_URL", "http://admin.nova.test")
os.environ.setdefault("ALLOWED_HOSTS", "testserver,localhost")
os.environ.setdefault("NOVA_EMAIL_FROM", "Nova <nova@nova.test>")
# Test-only key, committed on purpose.
os.environ.setdefault("NOVA_FERNET_KEYS", "tG9ABCWFaorMGi7O-cQrwRNfWatnLehyJjXiHuHpXP4=")
os.environ.setdefault("CSRF_TRUSTED_ORIGINS", "http://admin.nova.test")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://admin.nova.test")
# moto stands in for R2: AWS-style endpoint and region, dummy credentials.
os.environ.setdefault("R2_BUCKET", "nova-test-media")
os.environ.setdefault("R2_ACCESS_KEY_ID", "testing")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("R2_PUBLIC_URL", "https://media.nova.test")

from .base import *  # noqa: E402, F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

R2_REGION = "us-east-1"
# Tests must never reach Paystack; providers get an httpx.MockTransport.
PAYSTACK_API_BASE_URL = "https://paystack.invalid"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

INSTALLED_APPS = [*INSTALLED_APPS, "core.tests.tenant_testapp"]  # noqa: F405
