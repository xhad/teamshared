"""Standard API error envelope and exception mapping."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from teamshared.identity.rbac import PermissionDenied
from teamshared.ingestion.pipeline import IngestionRejected


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        {"error": {"code": code, "message": message, "request_id": request_id}},
        status_code=status,
    )


def map_exception(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ApiError):
        return error_response(request, exc.status, exc.code, exc.message)
    if isinstance(exc, PermissionDenied):
        return error_response(request, 403, "permission_denied", str(exc))
    if isinstance(exc, IngestionRejected):
        return error_response(request, 422, "ingestion_rejected", str(exc))
    if isinstance(exc, ValueError):
        return error_response(request, 400, "bad_request", str(exc))
    return error_response(request, 500, "internal_error", "internal server error")
