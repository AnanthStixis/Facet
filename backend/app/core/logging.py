"""Structured logging.

JSON in every environment except local, where a human-readable console renderer
is easier to work with. Log records carry the request id so a support ticket
quoting one id can be traced through the whole request.
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.core.config import settings

_REDACT_KEYS = {
    "password",
    "new_password",
    "current_password",
    "token",
    "refresh_token",
    "access_token",
    "authorization",
    "cookie",
    "mfa_code",
    "secret",
    "api_key",
    "openai_api_key",
}


def _redact(_logger, _method, event_dict):
    """Strip anything that must never reach a log aggregator."""
    for key in list(event_dict):
        if key.lower() in _REDACT_KEYS:
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if settings.debug else logging.INFO,
    )
    logging.getLogger("uvicorn.access").handlers.clear()

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if settings.environment == "local":
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.debug else logging.INFO
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "facet"):
    return structlog.get_logger(name)
