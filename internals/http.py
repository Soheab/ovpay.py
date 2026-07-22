from __future__ import annotations

import logging
import pathlib
from types import TracebackType
from typing import Any, ClassVar, Self

import aiohttp

from .auth import Authenticator
from .errors import (
    SessionExpiredError,
)

__all__ = ()

_logger = logging.getLogger("ovpay.http")

QueryParams = dict[str, str | int]


async def maybe_json(response: aiohttp.ClientResponse) -> Any:
    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        return await response.json()
    return await response.text()


class HTTPClient:
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
        token: str | pathlib.Path | None = None,
        cookie: str | pathlib.Path | None = None,
        base_url: str | None = None,
        session: aiohttp.ClientSession | None = None,
        rewrite_cookie_file: bool = False,
    ) -> None:
        if not token and not cookie:
            raise ValueError("Must provide either a static token or a browser cookie.")

        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self._cookie = cookie
        self._auth = Authenticator(
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
                if response.status != 401 or attempt == 1:
                    if response.status == 401:
                        raise SessionExpiredError(
                            f"OVpay API rejected the bearer token (401) for {url}"
                        )
                    response.raise_for_status()
                    return await maybe_json(response)

            # Outside the response context: refresh and retry with a fresh token.
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
                if response.status != 401 or attempt == 1:
                    if response.status == 401:
                        raise SessionExpiredError(
                            f"OVpay API rejected the bearer token (401) for {url}"
                        )
                    response.raise_for_status()
                    return await maybe_json(response)
            token = await self._auth.fallback_after_rejection(token)
        raise RuntimeError("Unreachable authentication retry state.")
