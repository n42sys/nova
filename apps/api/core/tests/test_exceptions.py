import pytest
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from core.exceptions import (
    Conflict,
    NotFound,
    PermissionDenied,
    ProviderUnavailable,
    ValidationFailed,
)


def _call(exc: Exception):
    class RaisingView(APIView):
        authentication_classes = []
        permission_classes = []

        def get(self, request):
            raise exc

    return RaisingView.as_view()(APIRequestFactory().get("/"))


def _assert_shape(data):
    assert set(data) == {"error"}
    assert set(data["error"]) == {"code", "message", "details"}


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (NotFound(), 404, "not_found"),
        (PermissionDenied(), 403, "permission_denied"),
        (ValidationFailed(), 400, "validation_failed"),
        (Conflict(), 409, "conflict"),
        (ProviderUnavailable(), 503, "provider_unavailable"),
    ],
)
def test_domain_exceptions_map_to_status_and_code(exc, status, code):
    response = _call(exc)

    assert response.status_code == status
    _assert_shape(response.data)
    assert response.data["error"]["code"] == code
    assert response.data["error"]["message"] == exc.default_message
    assert response.data["error"]["details"] is None


def test_domain_exception_carries_message_and_details():
    response = _call(ValidationFailed("Slug taken.", details={"slug": ["taken"]}))

    assert response.data == {
        "error": {
            "code": "validation_failed",
            "message": "Slug taken.",
            "details": {"slug": ["taken"]},
        }
    }


def test_drf_validation_error_uses_same_shape():
    response = _call(drf_exceptions.ValidationError({"name": ["Required."]}))

    assert response.status_code == 400
    _assert_shape(response.data)
    assert response.data["error"]["code"] == "validation_failed"
    assert response.data["error"]["details"] == {"name": ["Required."]}


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (drf_exceptions.ParseError(), 400, "parse_error"),
        (drf_exceptions.MethodNotAllowed("POST"), 405, "method_not_allowed"),
        (Http404(), 404, "not_found"),
        (DjangoPermissionDenied(), 403, "permission_denied"),
    ],
)
def test_drf_and_django_exceptions_use_same_shape(exc, status, code):
    response = _call(exc)

    assert response.status_code == status
    _assert_shape(response.data)
    assert response.data["error"]["code"] == code
    assert response.data["error"]["details"] is None


def test_unhandled_exceptions_are_not_swallowed():
    with pytest.raises(RuntimeError):
        _call(RuntimeError("boom"))


def test_provider_unavailable_sets_retry_after():
    response = _call(ProviderUnavailable())

    assert response.status_code == 503
    assert response["Retry-After"] == "30"


def test_other_domain_errors_set_no_retry_after():
    assert "Retry-After" not in _call(Conflict())
