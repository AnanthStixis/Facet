"""Application error types and their HTTP mapping.

Every error the API returns has a stable machine-readable `code`. The frontend
switches on the code, never on the human-readable message, so wording can be
changed or localised without breaking a client.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "bad_request"
    message: str = "The request could not be processed."

    def __init__(self, message: str | None = None, **details: Any) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)

    def to_response(self, request_id: str | None = None) -> JSONResponse:
        body: dict[str, Any] = {
            "error": {
                "code": self.code,
                "message": self.message,
            }
        }
        if self.details:
            body["error"]["details"] = self.details
        if request_id:
            body["error"]["request_id"] = request_id
        return JSONResponse(status_code=self.status_code, content=body)


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthenticated"
    message = "Authentication is required."


class InvalidCredentials(AuthenticationError):
    code = "invalid_credentials"
    # Deliberately identical whether the account is unknown or the password is
    # wrong. Distinguishing them turns the login form into an account
    # enumeration oracle.
    message = "Email or password is incorrect."


class AccountLocked(AuthenticationError):
    code = "account_locked"
    message = "Too many failed attempts. Try again later."


class AccountDisabled(AuthenticationError):
    code = "account_disabled"
    message = "Your login has been disabled by your organization. Please contact them."


class SessionExpired(AuthenticationError):
    code = "session_expired"
    message = "Your session has expired. Please sign in again."


class TokenReuseDetected(AuthenticationError):
    code = "token_reuse_detected"
    message = "This session was ended for security reasons. Please sign in again."


class PermissionDenied(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"
    message = "You do not have access to this resource."


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "The requested resource does not exist."


class Conflict(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "That action conflicts with the current state."


class ValidationFailed(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "validation_failed"
    message = "Some of the submitted values are not valid."


class RateLimited(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"
    message = "Too many requests. Please slow down."


class OrganizationInactive(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "organization_inactive"
    message = "This organization is not active. Contact your administrator."


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return exc.to_response(request_id=getattr(request.state, "request_id", None))


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last resort. Never leaks an internal message to the client."""
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "internal_error",
                "message": "Something went wrong on our side.",
                "request_id": request_id,
            }
        },
    )
