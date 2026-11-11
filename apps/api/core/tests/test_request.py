import pytest
from django.test import RequestFactory, override_settings

from core.request import get_client_ip


def _request(remote="10.0.0.2", forwarded=None):
    extra = {"REMOTE_ADDR": remote}
    if forwarded is not None:
        extra["HTTP_X_FORWARDED_FOR"] = forwarded
    return RequestFactory().get("/", **extra)


@override_settings(NOVA_TRUSTED_PROXY_COUNT=0)
def test_no_proxies_ignores_forwarded_header():
    assert get_client_ip(_request(forwarded="1.2.3.4")) == "10.0.0.2"


@pytest.mark.parametrize(
    ("proxies", "forwarded", "expected"),
    [
        (1, "203.0.113.9", "203.0.113.9"),
        (1, "6.6.6.6, 203.0.113.9", "203.0.113.9"),  # spoofed left-most hop ignored
        (2, "6.6.6.6, 203.0.113.9, 172.68.1.1", "203.0.113.9"),
        (2, "203.0.113.9", "10.0.0.2"),  # fewer hops than proxies: fall back
        (1, "not-an-ip", None),
        (1, "2001:db8::1", "2001:db8::1"),
    ],
)
def test_trusted_proxy_hops(proxies, forwarded, expected):
    with override_settings(NOVA_TRUSTED_PROXY_COUNT=proxies):
        assert get_client_ip(_request(forwarded=forwarded)) == expected


def test_missing_remote_addr():
    request = RequestFactory().get("/")
    request.META.pop("REMOTE_ADDR", None)

    assert get_client_ip(request) is None
