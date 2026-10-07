"""Silent re-login through OVpay's login server (Keycloak).

OVpay's NextAuth session can only renew its tokens for a limited time after the
original login (observed: about 6 hours). After that, /api/auth/session keeps
reporting RefreshTokenError. A browser gets past this by signing in again: the
login server still recognizes it through its own cookies on login.ovpay.nl, so
it hands out a new authorization code without asking for the email code again.

:class:`Relogin` replays that sign-in with those login.ovpay.nl cookies:

1. ``GET  /api/auth/csrf``             -> csrf token (+ NextAuth cookies)
2. ``POST /api/auth/signin/idp``       -> Keycloak authorization URL
                                          (+ state / PKCE cookies)
3. ``GET  <authorization URL>``        -> with the login.ovpay.nl cookies,
                                          redirects back with a code
4. ``GET  /api/auth/callback/idp?...`` -> sets a new NextAuth session cookie
"""

from __future__ import annotations

import datetime
import email.utils
import logging
import os
import pathlib
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

from .errors import InvalidCookieError, SessionExpiredError

if TYPE_CHECKING:
    from curl_cffi.requests import Response

    from .http import HTTPClient

__all__ = ("LoginCookieJar", "Relogin")

_logger = logging.getLogger("ovpay.auth")

WWW_BASE = "https://www.ovpay.nl"
PROVIDER_ID = "idp"
# Where NextAuth sends the browser after signing in; any page on the site works.
CALLBACK_PAGE = "/mijn-ovpay/reisoverzicht"
MAX_REDIRECTS = 10

_NAVIGATION_HEADERS: dict[str, str | None] = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Origin": None,
    "sec-fetch-mode": "navigate",
    "sec-fetch-dest": "document",
    "sec-fetch-site": "same-site",
    "Upgrade-Insecure-Requests": "1",
}


def _parse_cookie_pairs(raw: str) -> dict[str, str]:
    """Parse ``name=value`` pairs separated by ``;`` or newlines."""
    pairs: dict[str, str] = {}
    for part in raw.replace("\n", ";").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            pairs[name.strip()] = value.strip()
    return pairs


def _apply_set_cookies(store: dict[str, str], response: Response) -> bool:
    """Apply a response's Set-Cookie headers to `store`. Returns whether it changed.

    Parsed by hand rather than with http.cookies, which silently drops cookies
    with attributes or characters it doesn't know (Keycloak's values contain
    slashes, and it sends attributes like ``Version`` and ``Partitioned``).
    """
    changed = False
    now = datetime.datetime.now(tz=datetime.UTC)
    for header in response.headers.get_list("Set-Cookie"):
        if not header:
            continue
        pair, *attributes = header.split(";")
        name, sep, value = pair.strip().partition("=")
        if not sep or not name:
            continue
        value = value.strip().strip('"')
        deleted = not value
        for attribute in attributes:
            key, _, attr_value = attribute.strip().partition("=")
            key = key.strip().lower()
            if key == "max-age":
                try:
                    deleted = deleted or int(attr_value) <= 0
                except ValueError:
                    pass
            elif key == "expires":
                try:
                    expires = email.utils.parsedate_to_datetime(attr_value.strip())
                except (TypeError, ValueError):
                    continue
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=datetime.UTC)
                deleted = deleted or expires <= now
        if deleted:
            changed = store.pop(name, None) is not None or changed
        elif store.get(name) != value:
            store[name] = value
            changed = True
    return changed


def _header(store: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in store.items())


class LoginCookieJar:
    """The login.ovpay.nl cookies, kept up to date and optionally in a file."""

    def __init__(self, cookie: str | pathlib.Path) -> None:
        self._path: pathlib.Path | None = (
            cookie if isinstance(cookie, pathlib.Path) else None
        )
        raw = (
            cookie.read_text(encoding="utf-8")
            if isinstance(cookie, pathlib.Path)
            else cookie
        )
        self._cookies: dict[str, str] = _parse_cookie_pairs(raw)
        if not self._cookies:
            raise InvalidCookieError(
                "The login.ovpay.nl cookie is empty or has no name=value pairs."
            )
        if not any(name.startswith("KEYCLOAK_") for name in self._cookies):
            raise InvalidCookieError(
                "No KEYCLOAK_IDENTITY / KEYCLOAK_SESSION cookie found in the "
                f"login.ovpay.nl cookies: {list(self._cookies)}. Copy the cookies "
                "of login.ovpay.nl, not of www.ovpay.nl."
            )

    @property
    def cookies(self) -> dict[str, str]:
        return self._cookies

    def header(self) -> str:
        return _header(self._cookies)

    def update_from(self, response: Response) -> None:
        if _apply_set_cookies(self._cookies, response):
            self._save()

    def _save(self) -> None:
        if self._path is None:
            return
        temporary = self._path.with_name(f".{self._path.name}.tmp")
        temporary.write_text(self.header(), encoding="utf-8")
        os.replace(temporary, self._path)


class Relogin:
    """Signs in to www.ovpay.nl again using the login.ovpay.nl cookies."""

    def __init__(self, http: HTTPClient, jar: LoginCookieJar) -> None:
        self._http: HTTPClient = http
        self.jar: LoginCookieJar = jar

    async def _request(
        self, method: str, url: str, *, cookies: str, **kwargs: Any
    ) -> Response:
        headers: dict[str, str | None] = dict(kwargs.pop("headers", {}))
        headers["Cookie"] = cookies
        return await self._http._request_with_retry(
            cast("Any", method),
            url,
            headers=headers,
            allow_redirects=False,
            discard_cookies=True,
            **kwargs,
        )

    async def sign_in(self) -> str:
        """Run the sign-in flow and return the new NextAuth session cookie header.

        Raises SessionExpiredError when the login server no longer recognizes
        the login.ovpay.nl cookies (it shows its login form instead), meaning a
        manual login with the emailed code is needed.
        """
        www: dict[str, str] = {}

        # 1. csrf token
        response = await self._request(
            "GET",
            f"{WWW_BASE}/api/auth/csrf",
            cookies="",
            headers={"Accept": "application/json", "sec-fetch-site": "same-origin"},
        )
        response.raise_for_status()
        _apply_set_cookies(www, response)
        csrf_token = cast("dict[str, str]", response.json()).get("csrfToken")  # type: ignore
        if not csrf_token:
            raise SessionExpiredError("OVpay sign-in returned no csrf token")

        # 2. authorization URL
        response = await self._request(
            "POST",
            f"{WWW_BASE}/api/auth/signin/{PROVIDER_ID}",
            cookies=_header(www),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": WWW_BASE,
                "Referer": f"{WWW_BASE}{CALLBACK_PAGE}",
                "sec-fetch-site": "same-origin",
            },
            data={
                "csrfToken": csrf_token,
                "callbackUrl": f"{WWW_BASE}{CALLBACK_PAGE}",
                "json": "true",
            },
        )
        response.raise_for_status()
        _apply_set_cookies(www, response)
        url = cast("dict[str, str]", response.json()).get("url", "")  # type: ignore
        if not url or ("/api/auth/" in url and "error" in url):
            raise SessionExpiredError(f"OVpay sign-in did not start: {url!r}")

        # 3. login server; follow its redirects until it sends us back with a code
        callback_prefix = f"{WWW_BASE}/api/auth/callback/{PROVIDER_ID}"
        login_host = urlsplit(url).netloc
        for _ in range(MAX_REDIRECTS):
            if url.startswith(callback_prefix):
                break
            if urlsplit(url).netloc != login_host:
                raise SessionExpiredError(
                    f"OVpay login server redirected somewhere unexpected: {url}"
                )
            response = await self._request(
                "GET",
                url,
                cookies=self.jar.header(),
                headers={**_NAVIGATION_HEADERS, "Referer": f"{WWW_BASE}/"},
            )
            self.jar.update_from(response)
            location = response.headers.get("Location")
            if response.status_code not in (301, 302, 303, 307, 308) or not location:
                # A 200 here is the login form: the login server no longer
                # recognizes these cookies.
                raise SessionExpiredError(
                    "The login.ovpay.nl session has expired too (the login "
                    f"server answered {response.status_code} with its login "
                    "page instead of signing in), so a manual login is needed. "
                    "After logging in, also update the login.ovpay.nl cookies."
                )
            url = location if "://" in location else f"https://{login_host}{location}"
        else:
            raise SessionExpiredError("OVpay login server redirected too many times")

        query = urlsplit(url).query
        if "code=" not in query:
            raise SessionExpiredError(
                f"OVpay login server returned without a code: {query or url}"
            )

        # 4. callback: NextAuth exchanges the code and sets the session cookie
        response = await self._request(
            "GET",
            url,
            cookies=_header(www),
            headers={**_NAVIGATION_HEADERS, "sec-fetch-site": "same-site"},
        )
        _apply_set_cookies(www, response)
        location = response.headers.get("Location") or ""
        if "/api/auth/error" in location or "/api/auth/signin" in location:
            raise SessionExpiredError(f"OVpay rejected the sign-in: {location}")
        session = {
            name: value
            for name, value in www.items()
            if name.startswith("__Secure-next-auth.session-token")
        }
        if not session:
            raise SessionExpiredError(
                "OVpay sign-in finished without setting a session cookie "
                f"(status {response.status_code}, redirect {location!r})"
            )
        _logger.info("Signed in to OVpay again using the login.ovpay.nl cookies")
        return _header(session)
