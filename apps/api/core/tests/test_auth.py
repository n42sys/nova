import re
from unittest import mock

import pytest
from allauth.account.models import EmailAddress
from django.core import mail
from django.test import Client

from core.auth_adapter import AccountAdapter
from core.tests.factories import UserFactory
from core.tests.support import PASSWORD

pytestmark = pytest.mark.django_db

AUTH = "/_allauth/browser/v1"
ME = "/api/manage/me/"


def _login(browser, email, password=PASSWORD):
    return browser.send("post", f"{AUTH}/auth/login", {"email": email, "password": password})


def test_login_me_logout_flow(browser, verified_user):
    assert browser.get(ME).status_code == 401

    response = _login(browser, verified_user.email)
    assert response.status_code == 200
    assert response.json()["meta"]["is_authenticated"] is True

    response = browser.get(ME)
    assert response.status_code == 200
    assert response.json()["email"] == verified_user.email

    response = browser.send("delete", f"{AUTH}/auth/session")
    assert response.status_code == 401  # allauth reports the now-anonymous session
    assert browser.get(ME).status_code == 401


def test_login_email_is_case_insensitive(browser, verified_user):
    assert _login(browser, verified_user.email.upper()).status_code == 200


def test_wrong_password_is_rejected(browser, verified_user):
    assert _login(browser, verified_user.email, "wrong-password").status_code == 400
    assert browser.get(ME).status_code == 401


def test_unverified_email_cannot_log_in(browser):
    user = UserFactory(password=PASSWORD)
    EmailAddress.objects.create(user=user, email=user.email, verified=False, primary=True)

    response = _login(browser, user.email)

    assert response.status_code == 401
    pending = [flow for flow in response.json()["data"]["flows"] if flow.get("is_pending")]
    assert [flow["id"] for flow in pending] == ["verify_email"]
    assert browser.get(ME).status_code == 401


def test_login_by_code(browser, verified_user):
    with mock.patch.object(AccountAdapter, "generate_login_code", return_value="NOVA42"):
        response = browser.send("post", f"{AUTH}/auth/code/request", {"email": verified_user.email})
    assert response.status_code == 401  # login pending until the code is confirmed
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == [verified_user.email]
    assert re.search(r"\bNOVA42\b", mail.outbox[0].body)

    response = browser.send("post", f"{AUTH}/auth/code/confirm", {"code": "NOVA42"})

    assert response.status_code == 200
    assert browser.get(ME).json()["email"] == verified_user.email


def test_login_without_csrf_token_is_rejected(verified_user):
    strict = Client(enforce_csrf_checks=True)
    response = strict.post(
        f"{AUTH}/auth/login",
        {"email": verified_user.email, "password": PASSWORD},
        content_type="application/json",
    )

    assert response.status_code == 403
    assert strict.get(ME).status_code == 401


def test_self_signup_is_closed(browser):
    response = browser.send(
        "post", f"{AUTH}/auth/signup", {"email": "new@example.com", "password": PASSWORD}
    )

    assert response.status_code == 403
    assert browser.get(f"{AUTH}/config").json()["data"]["account"]["is_open_for_signup"] is False


def test_only_browser_client_is_exposed(browser):
    assert browser.get("/_allauth/app/v1/config").status_code == 404
