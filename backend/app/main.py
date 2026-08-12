"""FastAPI application."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import (
    AppError,
    ValidationFailed,
    app_error_handler,
    unhandled_error_handler,
)
from app.core.logging import configure_logging, get_logger
from app.db.session import engine

log = get_logger("facet.http")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    log.info(
        "startup",
        product=settings.product_name,
        environment=settings.environment,
        rate_limiter="redis" if settings.redis_url else "in-process",
        ai_enabled=settings.ai_enabled,
    )
    yield
    await engine.dispose()
    log.info("shutdown")


app = FastAPI(
    title=f"{settings.product_name} API",
    description=(
        "Multi-tenant feedback platform spanning employee, client, and proposal "
        "relationships."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
    openapi_url="/openapi.json" if not settings.is_production else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["authorization", "content-type", "x-facet-csrf"],
    expose_headers=["content-disposition"],
    max_age=600,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Attach a request id, time the request, and set baseline security headers."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    request.state.request_id = request_id
    started = time.perf_counter()

    response = await call_next(request)

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers["x-request-id"] = request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
    response.headers["x-frame-options"] = "DENY"
    response.headers["permissions-policy"] = "geolocation=(), microphone=(), camera=()"
    if "cache-control" not in response.headers:
        response.headers["cache-control"] = "no-store"
    if settings.is_production:
        response.headers["strict-transport-security"] = (
            "max-age=31536000; includeSubDomains"
        )

    log.info(
        "request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
        request_id=request_id,
        actor=getattr(request.state, "actor_id", None),
        org=getattr(request.state, "org_id", None),
    )
    return response


@app.exception_handler(AppError)
async def _app_error(request: Request, exc: AppError) -> JSONResponse:
    return await app_error_handler(request, exc)


@app.exception_handler(RequestValidationError)
async def _validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Reshape FastAPI's validation errors into the app's error envelope."""
    fields: dict[str, list[str]] = {}
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"] if part != "body")
        fields.setdefault(location or "body", []).append(error["msg"])
    return ValidationFailed(**fields).to_response(
        request_id=getattr(request.state, "request_id", None)
    )


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception(
        "unhandled_error",
        path=request.url.path,
        request_id=getattr(request.state, "request_id", None),
    )
    return await unhandled_error_handler(request, exc)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "product": settings.product_name,
        "environment": settings.environment,
        "version": app.version,
    }


@app.get("/api/v1/meta", tags=["meta"])
async def meta() -> dict[str, object]:
    """Public branding and policy values the sign-in screen needs before auth."""
    return {
        "product_name": settings.product_name,
        "tagline": settings.product_tagline,
        "vendor": settings.vendor_name,
        "password_min_length": settings.password_min_length,
        "ai_enabled": settings.ai_enabled,
        "self_registration_enabled": True,
    }


app.include_router(api_router)
