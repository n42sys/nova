from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class NovaError(Exception):
    """Base domain exception. Services raise these; the API layer maps them to responses."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = "error"
    default_message = "Something went wrong."

    def __init__(self, message: str | None = None, *, details: Any = None) -> None:
        self.message = str(message) if message is not None else self.default_message
        self.details = details
        super().__init__(self.message)


class NotFound(NovaError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    default_message = "Not found."


class PermissionDenied(NovaError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"
    default_message = "You do not have permission to perform this action."


class ValidationFailed(NovaError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "validation_failed"
    default_message = "Invalid input."


class Conflict(NovaError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    default_message = "Conflict."


def _error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Render domain and DRF exceptions as `{"error": {"code", "message", "details"}}`."""
    if isinstance(exc, NovaError):
        return Response(_error_body(exc.code, exc.message, exc.details), status=exc.status_code)

    if isinstance(exc, Http404):
        exc = drf_exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf_exceptions.PermissionDenied()

    response = drf_exception_handler(exc, context)
    if response is None or not isinstance(exc, drf_exceptions.APIException):
        return response

    if isinstance(exc, drf_exceptions.ValidationError):
        response.data = _error_body(
            ValidationFailed.code, ValidationFailed.default_message, response.data
        )
    elif isinstance(exc.detail, str):
        response.data = _error_body(exc.default_code, str(exc.detail))
    else:
        response.data = _error_body(exc.default_code, str(exc.default_detail), response.data)
    return response
