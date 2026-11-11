from django.apps import AppConfig


class TenantTestAppConfig(AppConfig):
    """Test-only app, installed in nova.settings.test. No migrations; see models.Widget."""

    name = "core.tests.tenant_testapp"
    label = "tenant_testapp"
    default_auto_field = "django.db.models.BigAutoField"
