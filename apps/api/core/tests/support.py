"""Test helpers shared by every app's tests (fixtures live in the root conftest.py)."""

from django.test import Client

PASSWORD = "correct-horse-battery"


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
