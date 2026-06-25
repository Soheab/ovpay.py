from __future__ import annotations

import asyncio
import base64
import datetime
import json
import logging
import pathlib
from types import TracebackType
from typing import TYPE_CHECKING, Any, ClassVar, Self

import aiohttp

from .errors import InvalidCookieError, NoTokenError, SessionExpiredError

if TYPE_CHECKING:
    from ._types import SessionData


__all__ = ()

_logger = logging.getLogger("ovpay.http")

QueryParams = dict[str, str | int]
SESSION_URL = "https://www.ovpay.nl/api/auth/session"
SESSION_COOKIE_NAME = "__Secure-next-auth.session-token"
REFRESH_LEEWAY_SECONDS = 120


async def maybe_json(response: aiohttp.ClientResponse) -> Any:
    """Return the response JSON if the content type is JSON, else None."""
    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        return await response.json()
    return await response.text()


class TokenManager:
    """Store a bearer token and refresh cookie-backed tokens when required."""

    LEEWAY: ClassVar[datetime.timedelta] = datetime.timedelta(
        seconds=REFRESH_LEEWAY_SECONDS
    )

    def __init__(
        self,
        http: HTTPClient,
        cookie: str | pathlib.Path | None,
        token: str | None,
        *,
        rewrite_cookie_file: bool = False,
    ) -> None:
        self._http: HTTPClient = http
        self._cookie: str | pathlib.Path | None = cookie
        self._token: str | None = token
        self._rewrite_cookie_file: bool = rewrite_cookie_file
        self._expires_at: datetime.datetime | None = None
        self._lock = asyncio.Lock()

    @staticmethod
    def normalize_cookie(cookie: str | pathlib.Path) -> str:
        """Return a Cookie header containing just the OVpay session cookie.

        Accepts any of:

        * A full Cookie header copied straight from the browser (the whole
          ``cookie:`` request header, or the rows from the Cookies panel) —
          ``name=value`` pairs separated by ``;`` or newlines. Only the
          session-token cookie (incl. its ``.0``/``.1`` chunks) is kept; the
          csrf-token, callback-url, etc. are dropped.
        * A single bare session-token value — prefixed with the session
          cookie name. Only valid when the token is small enough not to be
          chunked by NextAuth.
        """
        raw = (
            cookie.read_text() if isinstance(cookie, pathlib.Path) else cookie
        ).strip()
        if not raw:
            raise InvalidCookieError("Cookie cannot be empty.")

        # A full header / multiple cookies: pick out only the session chunks.
        if "=" in raw:
            pairs = [
                pair.strip()
                for pair in raw.replace("\n", ";").split(";")
                if pair.strip()
            ]
            session = [
                pair
                for pair in pairs
                if pair.split("=", 1)[0].strip().startswith(SESSION_COOKIE_NAME)
            ]
            if not session:
                names = [pair.split("=", 1)[0].strip() for pair in pairs]
                raise InvalidCookieError(
                    f"No '{SESSION_COOKIE_NAME}' cookie found in the provided "
                    f"cookies: {names}. Copy the full cookie header (or the "
                    "session-token rows) from your logged-in browser."
                )

            # Send chunks in index order so NextAuth reassembles them correctly.
            def chunk_index(pair: str) -> int:
                name = pair.split("=", 1)[0].strip()
                suffix = name[len(SESSION_COOKIE_NAME) :].lstrip(".")
                return int(suffix) if suffix.isdigit() else -1

            session.sort(key=chunk_index)
            return "; ".join(session)

        # A bare value with no "=". The csrf token is a 64+ char hex string
        # (often with a URL-encoded "%7C"); reject it early.
        if "%7c" in raw.lower() or (len(raw) <= 200 and "." not in raw):
            raise InvalidCookieError(
                "The provided value does not look like a session token (it "
                "resembles a csrf-token or session id). The session token is "
                "long and dot-separated."
            )
        return f"{SESSION_COOKIE_NAME}={raw}"

    @staticmethod
    def _jwt_exp(token: str) -> int | None:
        """Return the JWT expiration timestamp, if it can be decoded."""
        try:
            payload = token.split(".")[1]
            decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            return int(json.loads(decoded)["exp"])
        except (IndexError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    @property
    def expires_at(self) -> datetime.datetime | None:
        return self._expires_at

    @property
    def is_expired(self) -> bool:
        now = datetime.datetime.now(tz=datetime.UTC)
        return self.expires_at is not None and now >= self.expires_at - self.LEEWAY

    async def fetch_token(
        self,
        cookie: str | pathlib.Path,
    ) -> str:
        """Fetch a bearer token using an OVpay browser session cookie."""
        session = self._http._require_session()
        cookie_header = self.normalize_cookie(cookie)

        # Optionally rewrite a cookie file holding a full browser cookie dump
        # with just the extracted session cookie, so later reads are clean.
        # Opt-in: off by default to avoid mutating the user's file unexpectedly.
        if (
            self._rewrite_cookie_file
            and isinstance(cookie, pathlib.Path)
            and cookie.read_text().strip() != cookie_header
        ):
            cookie.write_text(cookie_header)

        async with session.get(
            SESSION_URL,
            headers={
                "Cookie": cookie_header,
                "Accept": "application/json",
                "User-Agent": "ovpay-wrapper/1.0",
            },
        ) as response:
            response.raise_for_status()
            data: SessionData = await response.json()
            token = data.get("token") or data.get("accessToken")
            error = data.get("error")
            # NextAuth surfaces refresh-flow failures (e.g. "RefreshTokenError")
            # while still returning a usable access token until its own expiry.
            # Only treat an error as fatal when no token came back with it.
            if error and not token:
                raise SessionExpiredError(
                    "OVpay session could not provide a bearer token",
                    error=error,
                )
        if not token:
            # An empty object means NextAuth did not recognize the cookie as a
            # session at all (wrong cookie pasted), as opposed to a known but
            # expired session (which carries `error`/`expires` keys).
            if not data:
                raise InvalidCookieError(
                    "OVpay returned an empty session: the provided cookie was "
                    "not recognized (wrong cookie, or all session chunks not "
                    "supplied)."
                )
            raise SessionExpiredError(
                "OVpay session returned no access token (logged out or cookie "
                f"expired); response keys: {list(data)}",
                error=error,
            )

        # Prefer the access token's own `exp` claim: NextAuth's `expires` field
        # tracks the session/refresh window (often weeks out) while the bearer
        # token itself typically lives only minutes/hours.
        jwt_exp = self._jwt_exp(token)
        if jwt_exp is not None:
            self._expires_at = datetime.datetime.fromtimestamp(jwt_exp, tz=datetime.UTC)
        elif exp := data.get("expires"):
            self._expires_at = datetime.datetime.fromisoformat(exp)
        else:
            # No expiry info in the token or session response — assume 10 minutes
            # so the refresh path still triggers rather than running forever with
            # a silently-expired token.
            self._expires_at = datetime.datetime.now(
                tz=datetime.UTC
            ) + datetime.timedelta(minutes=10)

        # If the session can no longer mint a fresh token, the access token
        # returned here may already be expired. Accepting it just produces a
        # 401 on the next API call (and a refresh loop), so fail loudly with a
        # clear "re-login" message instead.
        if self.is_expired:
            raise SessionExpiredError(
                "OVpay session returned an already-expired access token; the "
                "browser session can no longer be refreshed",
                error=error,
            )

        return token

    async def get_token(self) -> str:
        if not self._token:
            raise NoTokenError(
                "No bearer token is available. Provide a static token or a "
                "valid browser session cookie when constructing the client."
            )

        await self._refresh_if_needed()
        return self._token

    async def _refresh_if_needed(self) -> None:
        if not self._cookie or self._expires_at is None:
            return

        if not self.is_expired:
            return

        async with self._lock:
            if not self.is_expired:
                return

            await self._refresh()

    async def _refresh(self) -> str:
        _logger.debug("Refreshing bearer token (expired=%s)", self.is_expired)
        if not self._cookie:
            raise NoTokenError(
                "Cannot refresh a static bearer token: no session cookie was "
                "provided. Construct the client with a cookie to enable refresh."
            )

        self._token = await self.fetch_token(self._cookie)
        return self._token

    async def refresh(self) -> str:
        """Force a refresh of a cookie-backed bearer token."""
        async with self._lock:
            return await self._refresh()


class HTTPClient:
    """HTTP transport for authenticated and anonymous OVpay API requests."""

    BASE_URL: ClassVar[str] = "https://api.ovpay.nl"
    DEFAULT_HEADERS: ClassVar[dict[str, str]] = {
        "Accept": "*/*",
        "Origin": "https://www.ovpay.nl",
        "Referer": "https://www.ovpay.nl/mijn-ovpay/reisoverzicht",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
        ),
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "sec-fetch-dest": "empty",
    }

    def __init__(
        self,
        *,
        token: str | None = None,
        cookie: str | pathlib.Path | None = None,
        base_url: str | None = None,
        session: aiohttp.ClientSession | None = None,
        rewrite_cookie_file: bool = False,
    ) -> None:
        if not token and not cookie:
            raise ValueError("Must provide either a static token or a browser cookie.")

        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self._cookie = cookie
        self._auth = TokenManager(
            self, cookie=cookie, token=token, rewrite_cookie_file=rewrite_cookie_file
        )
        self._session: aiohttp.ClientSession | None = session
        self._session_owner: bool = session is None

    @property
    def is_open(self) -> bool:
        return self._session is not None and not self._session.closed

    async def start(self) -> None:
        """Open the underlying HTTP session and initialize cookie authentication."""
        if self.is_open:
            return

        self._session = self._session or aiohttp.ClientSession(
            headers=self.DEFAULT_HEADERS
        )
        if self._cookie:
            _logger.debug("Fetching initial bearer token from cookie")
            await self._auth._refresh()

    async def close(self) -> None:
        if self._session and self._session_owner:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    def _require_session(self) -> aiohttp.ClientSession:
        if not self.is_open or self._session is None:
            raise RuntimeError(
                "HTTP client not started. Call start() or use it as an async context manager."
            )
        return self._session

    async def get(
        self,
        path: str,
        *,
        params: QueryParams | None = None,
        authenticated: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        session = self._require_session()
        url = f"{self.base_url}/{path.lstrip('/')}"

        if not authenticated:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                return await maybe_json(response)

        token = await self._auth.get_token()
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {token}", **(extra_headers or {})}
            async with session.get(
                url,
                headers=headers,
                params=params,
            ) as response:
                # Retry a 401 once by forcing a token refresh — but only when a
                # cookie can mint a new token, and only on the first attempt.
                if response.status != 401 or attempt == 1 or not self._cookie:
                    if response.status == 401:
                        raise SessionExpiredError(
                            f"OVpay API rejected the bearer token (401) for {url}"
                        )
                    response.raise_for_status()
                    return await maybe_json(response)

            # Outside the response context: refresh and retry with a fresh token.
            token = await self._auth.refresh()

        raise RuntimeError("Unreachable authentication retry state.")

    async def get_anonymous(
        self, path: str, *, params: QueryParams | None = None
    ) -> Any:
        """Perform a JSON GET request without bearer authentication."""
        return await self.get(path, params=params, authenticated=False)

    async def post(
        self,
        path: str,
        *,
        json: object = None,
        extra_headers: dict[str, str] | None = None,
    ) -> object:
        session = self._require_session()
        url = f"{self.base_url}/{path.lstrip('/')}"
        token = await self._auth.get_token()
        for attempt in range(2):
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                **(extra_headers or {}),
            }
            async with session.post(url, headers=headers, json=json) as response:
                if response.status != 401 or attempt == 1 or not self._cookie:
                    if response.status == 401:
                        raise SessionExpiredError(
                            f"OVpay API rejected the bearer token (401) for {url}"
                        )
                    response.raise_for_status()
                    return await maybe_json(response)
            token = await self._auth.refresh()
        raise RuntimeError("Unreachable authentication retry state.")
