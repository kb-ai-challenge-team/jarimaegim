from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class APIError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        retry_after: int | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}
        self.retry_after = retry_after
        super().__init__(message)


def error_payload(request: Request, exc: APIError) -> dict[str, Any]:
    return {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "request_id": str(request.state.request_id),
            "retryable": exc.retryable,
            "details": exc.details,
        }
    }


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    headers = {"X-Request-Id": str(request.state.request_id)}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse(error_payload(request, exc), status_code=exc.status_code, headers=headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    safe_errors = []
    for item in exc.errors():
        safe_errors.append({"location": list(item.get("loc", ())), "message": item.get("msg", "invalid value"), "type": item.get("type")})
    error = APIError("VALIDATION_ERROR", "요청 값을 확인해 주세요.", 400, details={"fields": safe_errors})
    return await api_error_handler(request, error)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error = APIError("INTERNAL_ERROR", "요청을 처리하지 못했습니다.", 500, retryable=False)
    return await api_error_handler(request, error)



async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
    message = "요청한 경로 또는 리소스를 찾을 수 없습니다." if exc.status_code == 404 else "요청을 처리할 수 없습니다."
    return await api_error_handler(request, APIError(code, message, exc.status_code))
