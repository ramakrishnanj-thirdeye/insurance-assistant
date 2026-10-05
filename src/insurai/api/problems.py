"""RFC 7807 problem+json errors (spec 09 Behaviour). Thread errors are raised before any SSE stream opens."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_JSON = "application/problem+json"

TITLES: dict[str, str] = {
    "THREAD_NOT_FOUND": "Thread not found",
    "THREAD_FORBIDDEN": "Thread belongs to another identity",
    "THREAD_BUSY": "Thread is already running a turn",
    "REVIEW_PENDING": "Thread is waiting for a human review",
    "NO_PENDING_REVIEW": "Thread has no pending review",
    "IDENTITY_REQUIRED": "Identity headers missing or invalid",
    "IDENTITY_MISMATCH": "Identity in the request differs from the headers",
    "ACCESS_DENIED": "Not allowed for this persona",
    "NOT_FOUND": "Not found",
    "NOT_IMPLEMENTED": "Not available yet",
    "VALIDATION_ERROR": "Request validation failed",
    "HTTP_ERROR": "HTTP error",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str, **extra: Any) -> None:
        super().__init__(f"{status} {code}: {detail}")
        self.status, self.code, self.detail, self.extra = status, code, detail, extra


def problem(status: int, code: str, detail: str, **extra: Any) -> JSONResponse:
    body = {
        "type": f"urn:insurai:problem:{code.lower()}",
        "title": TITLES.get(code, code),
        "status": status,
        "code": code,
        "detail": detail,
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return problem(exc.status, exc.code, exc.detail, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return problem(422, "VALIDATION_ERROR", "The request body or query is invalid.", errors=errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        return problem(exc.status_code, code, str(exc.detail))
