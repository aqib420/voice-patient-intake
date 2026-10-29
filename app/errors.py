"""Consistent {"data": ..., "error": ...} envelope for every response,
including FastAPI's own validation errors and unexpected crashes."""
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app.errors")


class NotFoundError(Exception):
    def __init__(self, message: str = "Patient not found"):
        self.message = message


class DomainValidationError(Exception):
    """Business-rule failure outside Pydantic, e.g. clearing a required field."""

    def __init__(self, message: str, details: list | None = None):
        self.message = message
        self.details = details or []


def ok(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"data": jsonable_encoder(data), "error": None})


def fail(status_code: int, code: str, message: str, details: list | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"data": None, "error": {"code": code, "message": message, "details": details or []}},
    )


def _clean_validation_errors(errors: list[dict]) -> list[dict]:
    out = []
    for e in errors:
        loc = [str(p) for p in e.get("loc", ()) if p not in ("body", "query", "path")]
        msg = e.get("msg", "Invalid value").removeprefix("Value error, ")
        out.append({"field": ".".join(loc) or None, "message": msg})
    return out


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errors = exc.errors()
        if any(e.get("type") == "json_invalid" for e in errors):
            return fail(400, "bad_request", "Request body is not valid JSON.")
        return fail(422, "validation_error", "One or more fields are invalid.", _clean_validation_errors(errors))

    @app.exception_handler(DomainValidationError)
    async def _domain(_: Request, exc: DomainValidationError):
        return fail(422, "validation_error", exc.message, exc.details)

    @app.exception_handler(NotFoundError)
    async def _not_found(_: Request, exc: NotFoundError):
        return fail(404, "not_found", exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {400: "bad_request", 401: "unauthorized", 404: "not_found", 405: "method_not_allowed"}
        return fail(exc.status_code, code.get(exc.status_code, "http_error"), str(exc.detail))

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError):
        # Pydantic should catch everything first; reaching here means a DB
        # constraint caught something the schema missed.
        log.warning("DB constraint violation: %s", exc.orig)
        return fail(422, "constraint_violation", "The record violates a database constraint.")

    @app.exception_handler(SQLAlchemyError)
    async def _db(_: Request, exc: SQLAlchemyError):
        log.exception("Database error")
        return fail(500, "database_error", "A database error occurred. Please try again.")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error")
        return fail(500, "internal_error", "An unexpected error occurred.")
