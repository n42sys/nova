import logging

import httpx
import pytest
from django.conf import settings
from django.urls import reverse

from core.exceptions import ProviderUnavailable
from core.models import AuditLog, Role
from core.tests.factories import MembershipFactory
from payments.models import PaymentAccount
from payments.providers import PROVIDERS
from payments.providers.base import CredentialsRejected
from payments.providers.paystack import VERIFY_PATH, PaystackProvider
from payments.tests.factories import TEST_SECRET, PaymentAccountFactory

pytestmark = pytest.mark.django_db

OK_BODY = {
    "status": True,
    "message": "Payment session timeout retrieved",
    "data": {"payment_session_timeout": 30},
}


def _provider(handler) -> tuple[PaystackProvider, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return PaystackProvider(transport=httpx.MockTransport(record)), seen


def test_verify_makes_one_authenticated_read_only_request():
    provider, seen = _provider(lambda request: httpx.Response(200, json=OK_BODY))
    account = PaymentAccountFactory()

    provider.verify_credentials(account)

    [request] = seen
    assert request.method == "GET"
    assert str(request.url) == f"{settings.PAYSTACK_API_BASE_URL}{VERIFY_PATH}"
    assert VERIFY_PATH == "/integration/payment_session_timeout"
    assert request.headers["Authorization"] == f"Bearer {TEST_SECRET}"
    assert request.content == b""


@pytest.mark.parametrize("status", [401, 403])
def test_refused_keys(status):
    provider, _ = _provider(lambda request: httpx.Response(status, json={"status": False}))

    with pytest.raises(CredentialsRejected):
        provider.verify_credentials(PaymentAccountFactory())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="oops"),
        httpx.Response(502),
        httpx.Response(503),
        httpx.Response(429, json={"status": False}),
        httpx.Response(200, json={"status": False}),
        httpx.Response(200, text="<html>not json</html>"),
    ],
    ids=["500", "502", "503", "429", "200-status-false", "200-not-json"],
)
def test_provider_failures_are_unavailable(response):
    provider, _ = _provider(lambda request: response)

    with pytest.raises(ProviderUnavailable):
        provider.verify_credentials(PaymentAccountFactory())


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), httpx.ConnectTimeout("x")]
)
def test_unreachable_is_unavailable(error):
    def handler(request):
        raise error

    provider, _ = _provider(handler)

    with pytest.raises(ProviderUnavailable):
        provider.verify_credentials(PaymentAccountFactory())


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(401, json={"message": "Invalid key"}),
        lambda request: httpx.Response(500, text=request.headers["Authorization"]),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError(request.headers["Authorization"])),
    ],
    ids=["401", "500-echoing-key", "transport-error-echoing-key"],
)
def test_secret_never_in_exceptions_or_logs(handler, caplog):
    provider, _ = _provider(handler)
    caplog.set_level(logging.DEBUG)

    with pytest.raises((CredentialsRejected, ProviderUnavailable)) as exc_info:
        provider.verify_credentials(PaymentAccountFactory())

    assert TEST_SECRET not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert TEST_SECRET not in caplog.text


# Through the API


@pytest.fixture
def owner():
    return MembershipFactory(org_role=Role.OWNER)


def _verify(browser, owner, monkeypatch, handler):
    provider, _ = _provider(handler)
    monkeypatch.setitem(PROVIDERS, PaymentAccount.Provider.PAYSTACK, provider)
    account = PaymentAccountFactory(organization=owner.organization)
    browser.force_login(owner.user)
    url = reverse(
        "payment-account-verify",
        kwargs={"org": owner.organization.slug, "account_id": account.id},
    )
    return account, browser.send("post", url)


def test_api_verify_success(browser, owner, monkeypatch):
    account, response = _verify(
        browser, owner, monkeypatch, lambda request: httpx.Response(200, json=OK_BODY)
    )

    assert response.status_code == 200
    account.refresh_from_db()
    assert account.status == PaymentAccount.Status.VERIFIED and account.verified_at is not None


def test_api_verify_rejected(browser, owner, monkeypatch):
    account, response = _verify(
        browser, owner, monkeypatch, lambda request: httpx.Response(401, json={"status": False})
    )

    assert response.status_code == 400
    account.refresh_from_db()
    assert account.status == PaymentAccount.Status.PENDING


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_api_verify_paystack_5xx_is_503_with_retry_after(browser, owner, monkeypatch, status):
    _, response = _verify(browser, owner, monkeypatch, lambda request: httpx.Response(status))

    assert response.status_code == 503
    assert response["Retry-After"] == "30"
    assert response.json()["error"]["code"] == "provider_unavailable"
    assert not AuditLog.objects.for_org(owner.organization).exists()


def test_api_verify_unreachable_is_503(browser, owner, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("down")

    _, response = _verify(browser, owner, monkeypatch, handler)

    assert (response.status_code, response["Retry-After"]) == (503, "30")


def test_registered_provider_is_paystack():
    assert isinstance(PROVIDERS[PaymentAccount.Provider.PAYSTACK], PaystackProvider)
    assert PaymentAccount.Provider.DARAJA not in PROVIDERS
