from __future__ import annotations

import datetime

__all__ = (
    "AuthenticationError",
    "InvalidCookieError",
    "NoTokenError",
    "OVPayError",
    "SessionExpiredError",
    "TokenExpiredError",
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


class TokenExpiredError(AuthenticationError):
    """Raised when a static bearer token has passed its JWT expiry."""


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

    Attributes
    ----------
    error: :class:`str` | :data:`None`
        The error the session endpoint reported, e.g. ``"RefreshTokenError"``.
    logged_in_at: :class:`datetime.datetime` | :data:`None`
        When the browser login behind the session happened (the token's
        ``auth_time``). Identity providers cap how long a login can be kept
        alive, so the session's age at failure says whether such a limit was
        hit.
    last_refreshed_at: :class:`datetime.datetime` | :data:`None`
        When the session last issued a new token (the current token's
        ``iat``).
    """

    def __init__(
        self,
        message: str,
        *,
        error: str | None = None,
        logged_in_at: datetime.datetime | None = None,
        last_refreshed_at: datetime.datetime | None = None,
    ) -> None:
        self.error: str | None = error
        self.logged_in_at: datetime.datetime | None = logged_in_at
        self.last_refreshed_at: datetime.datetime | None = last_refreshed_at
        detail = f" (server reported {error!r})" if error else ""
        super().__init__(f"{message}{detail}{self._timeline()}\n\n{RELOGIN_HINT}")

    def _timeline(self) -> str:
        now = datetime.datetime.now(tz=datetime.UTC)
        parts: list[str] = []
        if self.logged_in_at is not None:
            age = _format_duration(now - self.logged_in_at)
            parts.append(
                f"logged in at {self.logged_in_at.isoformat(timespec='seconds')} "
                f"({age} ago)"
            )
        if self.last_refreshed_at is not None:
            parts.append(
                "last new token issued at "
                f"{self.last_refreshed_at.isoformat(timespec='seconds')}"
            )
        return f". Session {'; '.join(parts)}." if parts else ""

    def _fresh(self) -> SessionExpiredError:
        """Return a new instance with the same details.

        Raising one exception object repeatedly appends to its traceback each
        time, so a cached failure has to be re-raised as a copy.
        """
        clone = type(self).__new__(type(self))
        clone.__dict__.update(self.__dict__)
        Exception.__init__(clone, *self.args)
        return clone


def _format_duration(delta: datetime.timedelta) -> str:
    minutes = max(int(delta.total_seconds()) // 60, 0)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"
