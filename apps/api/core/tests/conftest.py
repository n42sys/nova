import pytest
from allauth.account.models import EmailAddress
from django.db import connection
from django.test import Client

from core.tests.factories import UserFactory
from core.tests.tenant_testapp.models import Widget

PASSWORD = "correct-horse-battery"


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Create the test-only tenant_testapp table once migrations have run."""
    with django_db_blocker.unblock(), connection.schema_editor() as editor:
        editor.create_model(Widget)


class BrowserClient(Client):
    """Test client that enforces CSRF like a browser and sends the current csrftoken."""

    def __init__(self, **kwargs):
        super().__init__(enforce_csrf_checks=True, **kwargs)

    def csrf(self) -> str:
        if "csrftoken" not in self.cookies:
            self.get("/_allauth/browser/v1/config")
        return self.cookies["csrftoken"].value

    def send(self, method: str, path: str, data=None, **extra):
        if data is not None:
            extra.update(data=data, content_type="application/json")
        return getattr(self, method)(path, HTTP_X_CSRFTOKEN=self.csrf(), **extra)


@pytest.fixture
def browser():
    return BrowserClient()


@pytest.fixture
def verified_user(db):
    user = UserFactory(password=PASSWORD)
    EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
    return user
