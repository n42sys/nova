import pytest
from django.db import connection

from core.tests.tenant_testapp.models import Widget


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Create the test-only tenant_testapp table once migrations have run."""
    with django_db_blocker.unblock(), connection.schema_editor() as editor:
        editor.create_model(Widget)
