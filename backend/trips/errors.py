"""Every API failure has the same shape: {"error": {code, message, fields?}}."""
from rest_framework import status
from rest_framework.exceptions import Throttled, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .providers.base import (
    InvalidRequest,
    NoRouteFound,
    ProviderError,
    RateLimited,
)
from .services.analyze import AnalysisExpired, ForecastMismatch

UNAVAILABLE_MESSAGE = "A data service is unavailable right now. Try again shortly."
BUSY_MESSAGE = "The data services are busy. Try again in a minute."


def _error(code: str, message: str, http_status: int, fields=None) -> Response:
    body = {"code": code, "message": message}
    if fields:
        body["fields"] = fields
    return Response({"error": body}, status=http_status)


def api_exception_handler(exc, context):
    if isinstance(exc, AnalysisExpired):
        return _error(
            "analysis_expired", "This analysis has expired. Run the trip again.",
            status.HTTP_404_NOT_FOUND,
        )
    if isinstance(exc, ForecastMismatch):
        return _error(
            "validation_error", "The forecast does not match this trip.",
            status.HTTP_400_BAD_REQUEST,
        )
    if isinstance(exc, NoRouteFound):
        return _error(
            "no_route", "No truck route was found between these places.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if isinstance(exc, InvalidRequest):
        return _error("validation_error", str(exc), status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, (RateLimited, Throttled)):
        return _error("rate_limited", BUSY_MESSAGE, status.HTTP_429_TOO_MANY_REQUESTS)
    if isinstance(exc, ProviderError):
        return _error(
            "upstream_unavailable", UNAVAILABLE_MESSAGE, status.HTTP_503_SERVICE_UNAVAILABLE
        )
    if isinstance(exc, ValidationError):
        return _error(
            "validation_error", "Check the highlighted fields.",
            status.HTTP_400_BAD_REQUEST, fields=exc.detail,
        )
    response = exception_handler(exc, context)
    if response is not None:
        return _error("request_failed", str(exc), response.status_code)
    return None
