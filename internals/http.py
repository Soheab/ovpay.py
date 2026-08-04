from __future__ import annotations

import logging
import pathlib
from types import TracebackType
from typing import TYPE_CHECKING, Any, ClassVar, Self

from curl_cffi.requests import AsyncSession

from .auth import Authenticator
from .errors import (
    SessionExpiredError,
)

if TYPE_CHECKING:
    from curl_cffi.requests import Response

__all__ = ()

_logger = logging.getLogger("ovpay.http")

QueryParams = dict[str, str | int]

# Matches a real browser's TLS/HTTP2 fingerprint (JA3, ALPN, header order,
# etc.) instead of aiohttp's, which is trivially distinguishable from
# genuine Chrome/Safari traffic by fingerprinting middleware. curl_cffi
# supplies the matching User-Agent and sec-ch-ua headers itself; don't
# hand-write those, or they'll disagree with the TLS fingerprint.
IMPERSONATE = "chrome"


def maybe_json(response: Response) -> Any:
    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        return response.json()  # type: ignore
    return response.text


class HTTPClient:
    BASE_URL: ClassVar[str] = "https://api.ovpay.nl"
    DEFAULT_HEADERS: ClassVar[dict[str, str | None]] = {
        "Accept": "*/*",
        "Accept-Language": "nl,en-US;q=0.9,en;q=0.8",
        "Origin": "https://www.ovpay.nl",
        "Referer": "https://www.ovpay.nl/mijn-ovpay/reisoverzicht",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        ),
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "sec-fetch-dest": "empty",
        # curl_cffi's impersonation profile models a top-level navigation;
        # a real XHR sends neither of these.
        "Sec-Fetch-User": None,
        "Upgrade-Insecure-Requests": None,
    }

    def __init__(
        self,
        *,
        token: str | pathlib.Path | None = None,
        cookie: str | pathlib.Path | None = None,
        base_url: str | None = None,
        session: AsyncSession[Response] | None = None,
        rewrite_cookie_file: bool = False,
    ) -> None:
        if not token and not cookie:
            raise ValueError("Must provide either a static token or a browser cookie.")

        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self._cookie = cookie
        self._auth = Authenticator(
            self, cookie=cookie, token=token, rewrite_cookie_file=rewrite_cookie_file
        )
        self._session: AsyncSession[Response] | None = session
        self._session_owner: bool = session is None

    @property
    def is_open(self) -> bool:
        return self._session is not None

    async def start(self) -> None:
        if self.is_open:
            return

        self._session = self._session or AsyncSession(
            headers=self.DEFAULT_HEADERS, impersonate=IMPERSONATE
        )
        if self._cookie:
            _logger.debug("Fetching initial bearer token from cookie")
            await self._auth._refresh()

    def replace_cookie(self, cookie: str | pathlib.Path) -> None:
        """Swap in a new session cookie without recreating the client."""
        self._cookie = cookie
        self._auth.replace_cookie(cookie)

    def replace_token(self, token: str | pathlib.Path) -> None:
        """Swap in a new static bearer token fallback without recreating the client."""
        self._auth.replace_token(token)

    def start_background_refresh(self, *, min_interval: float = 30.0) -> None:
        """Opt-in: proactively keep the cookie-backed token refreshed instead
        of only refreshing reactively on the next request."""
        self._auth.start_background_refresh(min_interval=min_interval)

    def stop_background_refresh(self) -> None:
        self._auth.stop_background_refresh()

    async def close(self) -> None:
        self._auth.stop_background_refresh()
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

    def _require_session(self) -> AsyncSession[Response]:
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
            response = await session.get(url, params=params)
            response.raise_for_status()
            return maybe_json(response)

        token = await self._auth.get_token()
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {token}", **(extra_headers or {})}
            response = await session.get(url, headers=headers, params=params)
            # Retry a 401 once by forcing a token refresh — but only when a
            # cookie can mint a new token, and only on the first attempt.
            if response.status_code != 401 or attempt == 1:
                if response.status_code == 401:
                    raise SessionExpiredError(
                        f"OVpay API rejected the bearer token (401) for {url}"
                    )
                response.raise_for_status()
                return maybe_json(response)

            token = await self._auth.fallback_after_rejection(token)

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
        json: dict[str, Any] | None = None,
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
            response = await session.post(url, headers=headers, json=json)
            if response.status_code != 401 or attempt == 1:
                if response.status_code == 401:
                    raise SessionExpiredError(
                        f"OVpay API rejected the bearer token (401) for {url}"
                    )
                response.raise_for_status()
                return maybe_json(response)
            token = await self._auth.fallback_after_rejection(token)
        raise RuntimeError("Unreachable authentication retry state.")
