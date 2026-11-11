"""Local development settings. Safe defaults so the stack runs from docker-compose alone."""

import os

os.environ.setdefault("SECRET_KEY", "django-insecure-dev-only")
os.environ.setdefault("DATABASE_URL", "postgres://nova:nova@localhost:5432/nova")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("NOVA_BASE_DOMAIN", "localhost")
os.environ.setdefault("NOVA_ADMIN_URL", "http://localhost:3000")
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1")
os.environ.setdefault("CSRF_TRUSTED_ORIGINS", "http://localhost:3000")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:3000")

from .base import *  # noqa: E402, F403

DEBUG = True
CORS_ALLOW_CREDENTIALS = True
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
