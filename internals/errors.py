from __future__ import annotations

__all__ = (
    "AuthenticationError",
    "InvalidCookieError",
    "NoTokenError",
    "OVPayError",
    "SessionExpiredError",
)

RELOGIN_HINT = (
    "Log in again at https://www.ovpay.nl, then copy your cookies into the "
    "client. Easiest: in the Network tab, open any request to ovpay.nl and "
    "copy the whole 'cookie:' request header. The client keeps only the "
    "session-token cookie and ignores the rest, so pasting everything is "
    "fine."
)


class OVPayError(Exception):
    """Base class for all errors raised by the OVpay wrapper."""


class AuthenticationError(OVPayError):
    """Raised when the client cannot authenticate against the OVpay API."""


class NoTokenError(AuthenticationError):
    """Raised when no bearer token or cookie is available to authenticate."""


class InvalidCookieError(AuthenticationError):
    """Raised when the provided cookie is malformed or the wrong cookie.

    The value is checked locally before any request is made — e.g. the
    csrf-token was pasted instead of the session cookie, or a session-token
    chunk is missing.
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"{message}\n\n{RELOGIN_HINT}")


class SessionExpiredError(AuthenticationError):
    """Raised when the browser session can no longer mint a valid token.

    The NextAuth session behind the cookie has expired and can no longer be
    refreshed, so a new login is required.
    """

    def __init__(self, message: str, *, error: str | None = None) -> None:
        self.error = error
        detail = f" (server reported {error!r})" if error else ""
        super().__init__(f"{message}{detail}\n\n{RELOGIN_HINT}")
