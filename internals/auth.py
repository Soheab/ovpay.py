from __future__ import annotations

import asyncio
import base64
import datetime
import json
import logging
import os
import pathlib
from http.cookies import SimpleCookie
from typing import TYPE_CHECKING, ClassVar, Self

import aiohttp

from .errors import (
    AuthenticationError,
    InvalidCookieError,
    NoTokenError,
    SessionExpiredError,
    TokenExpiredError,
)

if TYPE_CHECKING:
    from ._types import DecodedJWT, SessionData
    from .http import HTTPClient


SESSION_COOKIE_NAME = "__Secure-next-auth.session-token"
# OVpay's NextAuth callback keeps returning the current access token until its
# actual `exp` time. Refreshing minutes early therefore returns the same token
# and must not be mistaken for a failed/expired session.
REFRESH_LEEWAY_SECONDS = 0
SESSION_URL = "https://www.ovpay.nl/api/auth/session"

_logger = logging.getLogger("ovpay.auth")


class JWTToken:
    def __init__(self, data: DecodedJWT) -> None:
        self._update(data)

    @classmethod
    def from_token(cls, token: str | pathlib.Path) -> Self:
        _, data = cls.read(token)
        return cls(data)

    @staticmethod
    def decode(token: str) -> DecodedJWT:
        try:
            payload = token.split(".")[1]
            decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
            data: DecodedJWT = json.loads(decoded)
        except (IndexError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            raise InvalidCookieError(
                "The provided session cookie does not contain a valid JWT "
                "access token. The cookie may be malformed or expired."
            )
        return data

    @classmethod
    def read(cls, token: str | pathlib.Path) -> tuple[str, DecodedJWT]:
        """Resolve `token` to its raw string (reading a file at most once) and
        decode it, returning both."""
        if isinstance(token, pathlib.Path):
            token_path = token
            token = token_path.read_text(encoding="utf-8").strip()
            if not token:
                raise InvalidCookieError(f"Token file is empty: {token_path}")
        return token, cls.decode(token)

    def _update(self, data: DecodedJWT) -> None:
        self._data = data
        self._expires: int = data["exp"]
        self._issued_at: int = data["iat"]
        self._auth_time: int | None = data.get("auth_time")
        self._id: str | None = data.get("jti")
        self._sub: str | None = data.get("sub")
        self._iss: str = data["iss"]
        self._aud: str | list[str] = data["aud"]
        self._typ: str | None = data.get("typ")
        self._azp: str = data["azp"]
        self._sid: str | None = data.get("sid")
        self._realm_access: dict[str, list[str]] | None = data.get("realm_access")
        self._resource_access: dict[str, dict[str, list[str]]] | None = data.get(
            "resource_access"
        )
        self._scope: str = data["scope"]

    def replace_token(self, token: str) -> None:
        token_data = JWTToken.decode(token)
        self._update(token_data)

    @property
    def expires_at(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self._expires, tz=datetime.UTC)

    @property
    def issued_at(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self._issued_at, tz=datetime.UTC)

    @property
    def auth_time(self) -> datetime.datetime | None:
        if self._auth_time is None:
            return None
        return datetime.datetime.fromtimestamp(self._auth_time, tz=datetime.UTC)

    @property
    def id(self) -> str | None:
        return self._id

    @property
    def subject(self) -> str | None:
        return self._sub

    @property
    def issuer(self) -> str:
        return self._iss

    @property
    def audience(self) -> str | list[str]:
        return self._aud

    @property
    def type(self) -> str | None:
        return self._typ

    @property
    def authorized_party(self) -> str:
        return self._azp

    @property
    def session_id(self) -> str | None:
        return self._sid

    @property
    def realm_roles(self) -> list[str]:
        if self._realm_access is None:
            return []
        return self._realm_access.get("roles", [])

    @property
    def resource_access(self) -> dict[str, dict[str, list[str]]]:
        return self._resource_access or {}

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def is_expired(self) -> bool:
        return datetime.datetime.now(tz=datetime.UTC) >= self.expires_at


class CookieManager:
    """Owns the OVpay session cookie: normalization, storage, and rotation."""

    def __init__(
        self, cookie: str | pathlib.Path, *, rewrite_cookie_file: bool = False
    ) -> None:
        self._cookie: str | pathlib.Path = cookie
        self._cookie_path: pathlib.Path | None = (
            cookie if isinstance(cookie, pathlib.Path) else None
        )
        self._rewrite_cookie_file: bool = rewrite_cookie_file
        self._cached_header: str | None = None

    def replace_cookie(self, cookie: str | pathlib.Path) -> None:
        """Replace the cookie source and clear any cached normalized header."""
        self._cookie = cookie
        self._cookie_path = cookie if isinstance(cookie, pathlib.Path) else None
        self._cached_header = None

    @property
    def raw(self) -> str | pathlib.Path:
        return self._cookie

    @property
    def cached_header(self) -> str | None:
        """The last normalized Cookie header, without re-parsing the source."""
        return self._cached_header

    @staticmethod
    def normalize(cookie: str | pathlib.Path) -> str:
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

    def normalized(self) -> str:
        """Return the normalized Cookie header, using the cached value from a
        previous call/rotation instead of re-parsing the source when present."""
        if self._cached_header is not None:
            return self._cached_header

        raw = (
            self._cookie.read_text()
            if isinstance(self._cookie, pathlib.Path)
            else self._cookie
        )
        header = self.normalize(raw)

        # Opt-in: off by default to avoid mutating the user's file unexpectedly.
        if (
            self._rewrite_cookie_file
            and self._cookie_path is not None
            and raw.strip() != header
        ):
            self._cookie_path.write_text(header)

        self._cached_header = header
        return header

    def jwt(self) -> JWTToken:
        """Decode the session cookie's bearer token into a JWTToken.

        Raises InvalidCookieError if the cookie doesn't decode to a JWT.
        """
        cookie_header = self.normalized()
        return JWTToken.from_token(cookie_header.split("=", 1)[1])

    @staticmethod
    def extract_rotated(response: aiohttp.ClientResponse) -> str | None:
        """Extract a rotated, possibly chunked NextAuth session cookie."""
        chunks: list[tuple[int, str]] = []
        for header in response.headers.getall("Set-Cookie", []):
            parsed = SimpleCookie()
            parsed.load(header)
            for name, morsel in parsed.items():
                if not name.startswith(SESSION_COOKIE_NAME) or not morsel.value:
                    continue
                suffix = name[len(SESSION_COOKIE_NAME) :].lstrip(".")
                index = int(suffix) if suffix.isdigit() else -1
                chunks.append((index, f"{name}={morsel.value}"))

        if not chunks:
            return None
        chunks.sort(key=lambda item: item[0])
        return "; ".join(value for _, value in chunks)

    def store_rotated(self, cookie_header: str) -> None:
        """Use the latest session cookie and persist it when backed by a file."""
        self._cookie = cookie_header
        self._cached_header = cookie_header

        if self._cookie_path is not None:
            temporary = self._cookie_path.with_name(f".{self._cookie_path.name}.tmp")
            temporary.write_text(cookie_header, encoding="utf-8")
            os.replace(temporary, self._cookie_path)


class Authenticator:
    LEEWAY: ClassVar[datetime.timedelta] = datetime.timedelta(
        seconds=REFRESH_LEEWAY_SECONDS
    )

    def __init__(
        self,
        http: HTTPClient,
        cookie: str | pathlib.Path | None,
        token: str | pathlib.Path | None,
        *,
        rewrite_cookie_file: bool = False,
    ) -> None:
        self._http: HTTPClient = http
        self._cookie_manager: CookieManager | None = (
            CookieManager(cookie, rewrite_cookie_file=rewrite_cookie_file)
            if cookie is not None
            else None
        )
        self._static_token: str | None
        self._static_jwt: JWTToken | None
        if token:
            self._static_token, data = JWTToken.read(token)
            self._static_jwt = JWTToken(data)
        else:
            self._static_token = None
            self._static_jwt = None

        self._using_cookie: bool = False
        self._lock = asyncio.Lock()

        self._token_str: str | None = self._static_token
        self._token: JWTToken | None = self._static_jwt

    @property
    def token_expires_at(self) -> datetime.datetime | None:
        return self._token and self._token.expires_at

    @property
    def token_is_expired(self) -> bool:
        return bool(self._token and self._token.is_expired)

    @property
    def using_cookie(self) -> bool:
        return self._using_cookie

    @property
    def cookie_is_expired(self) -> bool:
        if self._cookie_manager is None:
            return False
        try:
            return self._cookie_manager.jwt().is_expired
        except InvalidCookieError:
            return True

    @property
    def is_expired(self) -> bool:
        now = datetime.datetime.now(tz=datetime.UTC)
        expires_at = self.token_expires_at
        return expires_at is not None and now >= expires_at - self.LEEWAY

    @property
    def is_actually_expired(self) -> bool:
        """Whether the bearer token has passed its real JWT expiry."""
        now = datetime.datetime.now(tz=datetime.UTC)
        expires_at = self.token_expires_at
        return expires_at is not None and now >= expires_at

    def _static_token_is_expired(self) -> bool:
        return bool(self._static_jwt and self._static_jwt.is_expired)

    def use_static_token(self) -> str:
        """Activate the configured static token as an authentication fallback."""
        if not self._static_token or self._static_jwt is None:
            raise NoTokenError("No static bearer token is available as a fallback.")
        if self._static_token_is_expired():
            raise TokenExpiredError(
                "Static OVpay bearer token expired at "
                f"{self._static_jwt.expires_at.isoformat()}; replace the token or "
                "restore the browser session cookie."
            )
        self._token_str = self._static_token
        self._token = self._static_jwt
        self._using_cookie = False
        _logger.debug("Using static bearer token fallback")
        return self._token_str

    async def fetch_token(self) -> str:
        if self._cookie_manager is None:
            raise NoTokenError(
                "Cannot fetch a bearer token: no session cookie was provided."
            )
        cookie_header = self._cookie_manager.normalized()

        token, error = await self._request_session(cookie_header)

        # NextAuth's refresh endpoint is occasionally still mid-rotation on the
        # first hit after the access token expires: it reports RefreshTokenError
        # but hands back the same stale (already-expired) token instead of a
        # freshly minted one. A second immediate request usually gets the
        # rotated token, so retry once before giving up.
        if error and self.is_actually_expired:
            _logger.debug(
                "Session endpoint returned an expired token with error=%s; "
                "retrying once",
                error,
            )
            raw = self._cookie_manager.raw
            token, error = await self._request_session(
                raw if isinstance(raw, str) else cookie_header
            )

        # The JWT `exp` claim alone isn't trustworthy here: NextAuth has been
        # observed returning error=RefreshTokenError alongside a token whose
        # `exp` claim is stale/wrong even though the token is still accepted
        # by the API. Only give up if the API itself actually rejects it.
        if (
            error
            and self.is_actually_expired
            and not await self._token_is_accepted(token)
        ):
            raise SessionExpiredError(
                "OVpay session returned an access token that the API rejected "
                "after a retry; the browser session can no longer be refreshed",
                error=error,
            )

        self._token_str = token
        self._token = JWTToken.from_token(token)
        self._using_cookie = True
        return token

    async def _token_is_accepted(self, token: str) -> bool:
        """Probe a cheap authenticated endpoint to check if the API actually
        accepts the token, rather than trusting its (possibly stale) `exp`.

        Only a genuine 2xx counts as accepted. Anything else — 401 (rejected),
        403 (WAF), 500 (malformed token), etc. — is treated as not proven
        valid, since only a real 2xx confirms the API actually honored it.
        """
        session = self._http._require_session()
        url = f"{self._http.base_url}/api/v1/PassengerAccounts"
        try:
            async with session.get(
                url, headers={"Authorization": f"Bearer {token}"}
            ) as response:
                return 200 <= response.status < 300
        except aiohttp.ClientError:
            return False

    async def _request_session(self, cookie_header: str) -> tuple[str, str | None]:
        """Hit the NextAuth session endpoint and return (token, error)."""
        session = self._http._require_session()
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
            rotated_cookie = CookieManager.extract_rotated(response)
            if rotated_cookie is not None and self._cookie_manager is not None:
                self._cookie_manager.store_rotated(rotated_cookie)
                self._http._cookie = rotated_cookie
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

        return token, error

    async def get_token(self) -> str:
        if not self._token:
            raise NoTokenError(
                "No bearer token is available. Provide a static token or a "
                "valid browser session cookie when constructing the client."
            )

        if not self._using_cookie and self.is_actually_expired:
            if self._cookie_manager is not None:
                try:
                    return await self.refresh()
                except AuthenticationError:
                    pass
            return self.use_static_token()

        await self._refresh_if_needed()
        if self._token_str is None:
            raise NoTokenError(
                "No bearer token is available. Provide a static token or a "
                "valid browser session cookie when constructing the client."
            )
        return self._token_str

    async def _refresh_if_needed(self) -> None:
        if (
            not self._using_cookie
            or self._cookie_manager is None
            or self._token is None
        ):
            return

        if not self.is_expired:
            return

        async with self._lock:
            if not self.is_expired:
                return

            await self._refresh()

    async def _refresh(self) -> str:
        _logger.debug("Refreshing bearer token (expired=%s)", self.is_expired)
        if self._cookie_manager is None:
            raise NoTokenError(
                "Cannot refresh a static bearer token: no session cookie was "
                "provided. Construct the client with a cookie to enable refresh."
            )

        try:
            return await self.fetch_token()
        except AuthenticationError:
            if self._static_token:
                return self.use_static_token()
            raise

    async def refresh(self) -> str:
        """Force a refresh of a cookie-backed bearer token."""
        async with self._lock:
            return await self._refresh()

    async def fallback_after_rejection(self, rejected_token: str) -> str:
        """Switch to the other configured credential after an API 401."""
        if self._using_cookie and self._static_token:
            fallback = self.use_static_token()
        elif self._cookie_manager is not None:
            fallback = await self._refresh()
        else:
            raise SessionExpiredError("OVpay API rejected the static bearer token")

        if fallback == rejected_token:
            raise SessionExpiredError(
                "OVpay API rejected the bearer token and the fallback produced "
                "the same token"
            )
        return fallback
