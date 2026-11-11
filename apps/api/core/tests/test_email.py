from unittest import mock

import pytest
import resend
from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection, send_mail

pytestmark = pytest.mark.django_db

BACKEND = "core.email.ResendCeleryEmailBackend"


def test_test_settings_use_locmem():
    assert settings.EMAIL_BACKEND == "django.core.mail.backends.locmem.EmailBackend"


def test_resend_backend_queues_after_commit(django_capture_on_commit_callbacks):
    message = EmailMultiAlternatives(
        subject="Your sign-in code",
        body="Code: NOVA42",
        from_email="Nova <nova@nova.test>",
        to=["ada@example.com"],
        reply_to=["support@nova.test"],
    )
    message.attach_alternative("<p>Code: NOVA42</p>", "text/html")

    with mock.patch("core.tasks.resend.Emails.send") as resend_send:
        with django_capture_on_commit_callbacks(execute=False) as callbacks:
            sent = get_connection(BACKEND).send_messages([message])
        assert sent == 1
        resend_send.assert_not_called()  # nothing leaves before commit

        for callback in callbacks:
            callback()

    resend_send.assert_called_once_with(
        {
            "from": "Nova <nova@nova.test>",
            "to": ["ada@example.com"],
            "subject": "Your sign-in code",
            "text": "Code: NOVA42",
            "reply_to": ["support@nova.test"],
            "html": "<p>Code: NOVA42</p>",
        }
    )


def test_resend_backend_defaults_from_address(django_capture_on_commit_callbacks):
    with (
        mock.patch("core.tasks.resend.Emails.send") as resend_send,
        django_capture_on_commit_callbacks(execute=True),
    ):
        send_mail("Hi", "Body", None, ["ada@example.com"], connection=get_connection(BACKEND))

    assert resend_send.call_args.args[0]["from"] == settings.DEFAULT_FROM_EMAIL


def test_resend_api_key_comes_from_settings(settings, django_capture_on_commit_callbacks):
    settings.RESEND_API_KEY = "re_test_key"
    with (
        mock.patch("core.tasks.resend.Emails.send"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        send_mail("Hi", "Body", None, ["ada@example.com"], connection=get_connection(BACKEND))

    assert resend.api_key == "re_test_key"
