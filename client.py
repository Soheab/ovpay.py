from __future__ import annotations

import pathlib
from collections.abc import Callable
from datetime import date, datetime
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

import aiohttp

from .internals.http import HTTPClient
from .internals.pagination import Paginator
from .models import (
    Address,
    AnonymousConfig,
    ApiVersion,
    Customer,
    FaqArticle,
    FaqArticlesPage,
    FaqTopic,
    OvPasPrice,
    PassengerAccount,
    Payment,
    PaymentReceipt,
    PaymentsPage,
    SearchResponse,
    SearchSuggestions,
    TransitAccount,
    TransitAccountProducts,
    TripDetails,
    TripItem,
    TripsPage,
    WebConfig,
)
from .poller import OVPayPoller

if TYPE_CHECKING:
    from .internals._types import (
        AddressData,
        AnonymousConfigData,
        ApiVersionData,
        CardProductsData,
        CustomerData,
        FaqArticleData,
        FaqArticlesPageData,
        FaqTopicData,
        OvPasPriceData,
        PassengerAccountData,
        PaymentReceiptData,
        PaymentsPageData,
        SearchResponseData,
        SearchSuggestionsData,
        TransitAccountData,
        TripDetailsData,
        TripsPageData,
        WebConfigData,
    )
    from .poller import _BalanceCB, _PaymentCB, _TripCB


def _iso(value: date | datetime | str) -> str:
    return value if isinstance(value, str) else value.isoformat()


class ExportQuery:
    """Builder for the trip-export filter options.

    Mirrors the options available on the OVpay "Declareren" page.

    Usage::

        query = (
            ExportQuery("2026-06-01", "2026-06-25")
            .exclude_transit_accounts("transit-account-token-to-skip")
            .exclude_transport("BUS", "TRAM")
            .exclude_zero_amount()
        )
        trips = await client.export_trips_query(query)
    """

    TRANSPORT_OPTIONS = ("TRAIN", "BUS", "TRAM", "METRO", "WATERBUS")

    def __init__(
        self,
        from_date: date | datetime | str,
        to_date: date | datetime | str,
    ) -> None:
        self._from = _iso(from_date)
        self._to = _iso(to_date)
        self._excluded_xtats: list[str] = []
        self._excluded_transport: list[str] = []
        self._exclude_post_paid_non_fixed: bool = False
        self._exclude_zero_amount: bool = False
        self._excluded_trip_ids: list[int] = []

    def exclude_transit_accounts(self, *xtats: str) -> ExportQuery:
        """Exclude one or more transit accounts (cards) by their XTAT token."""
        self._excluded_xtats.extend(xtats)
        return self

    def exclude_transport(self, *modes: str) -> ExportQuery:
        """Exclude transport modes. Valid values: TRAIN, BUS, TRAM, METRO, WATERBUS."""
        self._excluded_transport.extend(m.upper() for m in modes)
        return self

    def exclude_post_paid_non_fixed(self) -> ExportQuery:
        """Exclude post-paid trips without a fixed fare."""
        self._exclude_post_paid_non_fixed = True
        return self

    def exclude_zero_amount(self) -> ExportQuery:
        """Exclude trips with a €0 fare."""
        self._exclude_zero_amount = True
        return self

    def exclude_trips(self, *trip_ids: int) -> ExportQuery:
        """Exclude specific trips by their numeric ID."""
        self._excluded_trip_ids.extend(trip_ids)
        return self

    def _to_body(self, offset: int = 0) -> dict[str, object]:
        return {
            "from": self._from,
            "to": self._to,
            "excludedXtats": list(self._excluded_xtats),
            "excludedTransportOptions": list(self._excluded_transport),
            "hasPostPaidNonFixedTripsExcluded": self._exclude_post_paid_non_fixed,
            "hasZeroAmountTripsExcluded": self._exclude_zero_amount,
            "excludedTripIds": list(self._excluded_trip_ids),
        }


class OVPayClient:
    """Unofficial async OVpay API client.

    The api.ovpay.nl WAF requires Origin/Referer/a browser UA.

    Usage (async context manager — recommended)
    -------------------------------------------
    Static token (expires in ~1 h, no auto-refresh):
        async with OVPayClient(token="eyJ...") as client:
            cards = await client.get_transit_accounts()

        async with OVPayClient(token=pathlib.Path("ovpay.token")) as client:
            cards = await client.get_transit_accounts()

    Browser cookie (auto-refreshes, lasts ~weeks):
        async with OVPayClient(cookie=pathlib.Path("cookies.txt")) as client:
            cards = await client.get_transit_accounts()

    Cookie with a static-token fallback:
        async with OVPayClient(
            cookie=pathlib.Path("cookies.txt"),
            token=pathlib.Path("ovpay.token"),
        ) as client:
            cards = await client.get_transit_accounts()

    Manual session lifecycle:
        client = OVPayClient(token="eyJ...")  # or cookie=pathlib.Path("cookies.txt")
        await client.start()

        try:
            ...
        finally:
            await client.close()

    Parameters
    ----------
    token: :class:`str` | :class:`pathlib.Path` | :data:`None`
        A bearer token (JWT) for the OVpay API. If provided, the client will use
        this token for authentication. The token expires after ~1 hour and will not
        be refreshed automatically. A pathlib.Path is read as a UTF-8 token file;
        surrounding whitespace is removed. When both `token` and `cookie` are
        provided, the cookie is preferred and the static token is retained as a
        fallback.
    cookie: :class:`str` | :class:`pathlib.Path` | :data:`None`
        A browser session cookie for the OVpay API. If provided, the client will
        use this cookie to fetch a bearer token and will refresh it automatically
        when it expires. The cookie can be a string or a pathlib.Path to a file
        containing the cookie value. You may paste a full browser cookie header;
        only the "__Secure-next-auth.session-token" cookie (incl. its .0/.1
        chunks) is kept.
    session: :class:`aiohttp.ClientSession` | :data:`None`
        An optional aiohttp.ClientSession to use for HTTP requests. If not provided,
        the client will create its own session and manage its lifecycle.
    rewrite_cookie_file: :class:`bool`
        When True and `cookie` is a file path, the file is rewritten in place
        with just the extracted session cookie after the first successful
        fetch. Defaults to False (the file is left untouched).
    enable_poller: :class:`bool`
        When True, the client will start a background poller that fetches trips,
        payments, and balance changes on a fixed interval. Defaults to False.
    poller_interval: :class:`float`
        The interval in seconds at which the poller fetches data. Defaults to 60.
    """

    # fmt: off
    def __init__(
        self,
        *,
        token: str | pathlib.Path | None = None,
        cookie: str | pathlib.Path | None = None,
        session: aiohttp.ClientSession | None = None,
        rewrite_cookie_file: bool = False,
        enable_poller: bool = False,
        poller_interval: float = 60.0,
    ) -> None:
    # fmt: on
        self._http = HTTPClient(
            token=token,
            cookie=cookie,
            session=session,
            rewrite_cookie_file=rewrite_cookie_file,
        )
        self._poller: OVPayPoller | None = OVPayPoller(self, interval=poller_interval) if enable_poller else None

    @property
    def poller_interval(self) -> float | None:
        """:class:`float` | None: The polling interval in seconds, or None if the poller is disabled."""
        return self._poller.interval if self._poller else None

    @poller_interval.setter
    def poller_interval(self, value: float) -> None:
        if not self._poller:
            raise RuntimeError("Poller is not enabled")
        self._poller.interval = value

    def event(self, name: str | None = None) -> Callable[[_TripCB | _PaymentCB | _BalanceCB], _TripCB | _PaymentCB | _BalanceCB]:
        """Decorator to register an event callback on the poller.

        The poller must be enabled for this to work. See :class:`OVPayPoller`
        for available events.

        Parameters
        ----------
        name: :class:`str` | :data:`None`
            The name of the event to register the callback for. If None, the
            decorator will use the function name as the event name.

            Event names must be prefixed with "on_" and match the names of the events in :class:`OVPayPoller`.

        Returns
        -------
        Callable[..., Coroutine[Any, Any, None]]
            A decorator that registers the decorated function as a callback for the specified event.
        """
        poller = self._poller
        if not poller:
            raise RuntimeError("Poller is not enabled, thus event registration is not available.")
        
        def decorator(func: _TripCB | _PaymentCB | _BalanceCB) -> _TripCB | _PaymentCB | _BalanceCB:
            event_name = name or func.__name__
            if not event_name.startswith("on_"):
                current = event_name.split("_", 1)[0]
                msg = f"Event name must start with 'on_', not '{current}_'. Use the 'name' parameter to override the function name if needed."
                raise ValueError(msg)

            event_name = event_name.removeprefix("on_")
            poller._register_event(event_name, func)
            return func

        return decorator

    async def start(self) -> None:
        """Starts the underlying aiohttp session and poller (if enabled)."""
        await self._http.start()
        if self._poller:
            await self._poller.start()

    async def close(self) -> None:
        """Closes the underlying aiohttp session and poller (if enabled).
        
        This will not close the session provided by the user.
        """
        if self._poller:
            self._poller.stop()

        await self._http.close()

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

    async def get_transit_accounts(self, *, with_personalization: bool = False) -> list[TransitAccount]:
        """Return all transit accounts for the authenticated user.

        Each :class:`TransitAccount` represents a physical or virtual card
        (*pas* / *betaalmiddel*) linked to the account.

        Parameters
        ----------
        with_personalization: :class:`bool`, optional
            When :data:`True`, hits the ``includepersonalization`` endpoint which
            guarantees :attr:`~TransitAccount.personalization` (name, color, order)
            is populated even for accounts that would otherwise return :data:`None`.
            Defaults to :data:`False`.

        Returns
        -------
        :class:`list`[:class:`TransitAccount`]
            Every transit account linked to the authenticated user.
        """
        url = "/api/v1/TransitAccounts"
        if with_personalization:
            url += "/includepersonalization"
        d: list[TransitAccountData] = await self._http.get(url)
        return [TransitAccount.from_dict(self, d) for d in d]

    async def find_transit_account(
        self,
        *,
        card_number: str | None = None,
        medium_id: str | None = None,
        hashed_medium_id: str | None = None,
    ) -> list[TransitAccount]:
        """Look up transit accounts by physical card identifiers.

        All three parameters query ``GET /api/v1/TransitAccounts`` with a
        filter — pass exactly one. Useful when you have a card number from the
        OV-chipkaart portal but need the OVpay XTAT/XBOT tokens.

        Parameters
        ----------
        card_number: :class:`str` or :data:`None`, optional
            The 16-digit card number printed on the physical card (``cardNumber``).
        medium_id: :class:`str` or :data:`None`, optional
            The medium ID from the OV-chipkaart portal (``mediumId``); equivalent
            to *card_number* for personal OV-chipkaarts.
        hashed_medium_id: :class:`str` or :data:`None`, optional
            The base64url-encoded hashed medium ID (``hashedMediumId``).

        Returns
        -------
        :class:`list`[:class:`TransitAccount`]
            Matching transit accounts (typically one).
        """
        if sum(x is not None for x in (card_number, medium_id, hashed_medium_id)) != 1:
            raise ValueError("Provide exactly one of card_number, medium_id, or hashed_medium_id.")
        if card_number is not None:
            params: dict[str, str | int] = {"cardNumber": card_number}
        elif medium_id is not None:
            params = {"mediumId": medium_id}
        else:
            params = {"hashedMediumId": hashed_medium_id}  # type: ignore[arg-type]
        raw: list[TransitAccountData] = await self._http.get("/api/v1/TransitAccounts", params=params)
        return [TransitAccount.from_dict(self, a) for a in raw]

    async def get_transit_account(self, transit_account_token: str) -> TransitAccount:
        """Return the latest details for a single transit account (card).

        Parameters
        ----------
        transit_account_token: :class:`str`
            The XTAT token (:attr:`TransitAccount.xtat`) of the transit account.

        Returns
        -------
        :class:`TransitAccount`
            Up-to-date details for the requested transit account.
        """
        raw: TransitAccountData = await self._http.get(
            f"/api/v1/TransitAccounts/{transit_account_token}"
        )
        return TransitAccount.from_dict(self, raw)

    async def get_token_details(self, back_office_token: str) -> TransitAccount:
        """Return transit account details looked up by back-office token (XBOT).

        Use this when you have the XBOT but not the XTAT, e.g. when working with
        a token embedded inside a :class:`TripDetails` response.

        Parameters
        ----------
        back_office_token: :class:`str`
            The XBOT token (:attr:`TransitAccount.xbot`) of the transit account.

        Returns
        -------
        :class:`TransitAccount`
            Up-to-date details for the transit account identified by the XBOT.
        """
        raw: TransitAccountData = await self._http.get(
            f"/api/v1/Tokens/{back_office_token}"
        )
        return TransitAccount.from_dict(self, raw)

    async def get_transit_account_products(self, transit_account_token: str) -> TransitAccountProducts:
        """Return products and age-discount information for a transit account (card).

        Parameters
        ----------
        transit_account_token: :class:`str`
            The XTAT token (:attr:`TransitAccount.xtat`) of the transit account.

        Returns
        -------
        :class:`TransitAccountProducts`
            Products list and age-discount profile for the transit account.
        """
        raw: CardProductsData = await self._http.get(
            f"/api/v2/Products/{transit_account_token}"
        )
        return TransitAccountProducts.from_dict(raw)

    async def _get_trips(self, transit_account_token: str, *, offset: int = 0) -> TripsPage:
        raw: TripsPageData = await self._http.get(
            f"/api/v3/Trips/{transit_account_token}", params={"offset": offset}
        )
        return TripsPage.from_dict(self, raw)

    def get_trips(
        self, transit_account_token: str, *, limit: int | None = None
    ) -> Paginator[TripItem]:
        """Return a paginator over all trips for a transit account (card).

        Pagination is handled internally. Await the paginator to collect every
        trip into a list, or iterate with ``async for`` to stream page-by-page::

            trips = await client.get_trips(transit_account.xtat)
            async for trip in client.get_trips(transit_account.xtat):
                ...

        Parameters
        ----------
        transit_account_token: :class:`str`
            The XTAT token (:attr:`TransitAccount.xtat`) of the transit account.
        limit: :class:`int` or :data:`None`, optional
            Maximum number of trips to return. :data:`None` (default) returns all.

        Returns
        -------
        :class:`Paginator`[:class:`TripItem`]
            Paginator that yields :class:`TripItem` instances.
        """
        return Paginator(
            lambda offset: self._get_trips(transit_account_token, offset=offset), limit=limit
        )

    async def get_trip_details(self, token: str, id: int) -> TripDetails:
        """Return full detail for a single trip, including corrections and discounts.

        Parameters
        ----------
        token: :class:`str`
            The back-office token (:attr:`Trip.xbot`) of the trip.
        id: :class:`int`
            The numeric trip ID (:attr:`Trip.id`).

        Returns
        -------
        :class:`TripDetails`
            Full trip detail, including the transit account token, any fare
            corrections, age discounts, product discounts, and day-capping info.
        """
        raw: TripDetailsData = await self._http.get(f"/api/v3/Trips/{token}/{id}")
        return TripDetails.from_dict(self, raw)

    async def _export_trips(
        self,
        query: ExportQuery,
        *,
        offset: int = 0,
    ) -> TripsPage:
        raw = await self._http.post(
            "/api/v2/TripExport/trips",
            json=query._to_body(offset),
            extra_headers={"Referer": "https://www.ovpay.nl/"},
        )
        # The export endpoint returns a flat list, not a paginated envelope.
        if isinstance(raw, list):
            paged: TripsPageData = {
                "offset": offset,
                "batchSize": len(raw),
                "endOfListReached": True,
                "items": raw,
            }
            return TripsPage.from_dict(self, paged)
        return TripsPage.from_dict(self, raw)

    def export_trips(
        self,
        from_date: date | datetime | str,
        to_date: date | datetime | str,
        *,
        limit: int | None = None,
    ) -> Paginator[TripItem]:
        """Return a paginator over all exported trips in a date range.

        Uses the Trip Export API (``/api/v2/TripExport/trips``), which supports
        broader date ranges than the regular trips endpoint. Pagination is handled
        internally::

            trips = await client.export_trips("2026-01-01", "2026-01-31")
            async for trip in client.export_trips("2026-01-01", "2026-01-31"):
                ...

        For filtering by transit account, transport mode, or fare amount, build
        an :class:`ExportQuery` and pass it to :meth:`export_trips_query` instead.

        Parameters
        ----------
        from_date: :class:`date` or :class:`datetime` or :class:`str`
            Start of the date range, as a :class:`date`, :class:`datetime`, or ISO string.
        to_date: :class:`date` or :class:`datetime` or :class:`str`
            End of the date range, as a :class:`date`, :class:`datetime`, or ISO string.
        limit: :class:`int` or :data:`None`, optional
            Maximum number of trips to return. :data:`None` (default) returns all.

        Returns
        -------
        :class:`Paginator`[:class:`TripItem`]
            Paginator that yields :class:`TripItem` instances.
        """
        return self.export_trips_query(
            ExportQuery(from_date, to_date), limit=limit
        )

    def export_trips_query(
        self,
        query: ExportQuery,
        *,
        limit: int | None = None,
    ) -> Paginator[TripItem]:
        """Return a paginator over exported trips using a pre-built query.

        Like :meth:`export_trips` but accepts a fully configured
        :class:`ExportQuery` for fine-grained filtering (exclude transit accounts,
        transport modes, zero-amount trips, etc.).

        Parameters
        ----------
        query: :class:`ExportQuery`
            A configured :class:`ExportQuery` instance specifying the date range
            and any filters to apply.
        limit: :class:`int` or :data:`None`, optional
            Maximum number of trips to return. :data:`None` (default) returns all.

        Returns
        -------
        :class:`Paginator`[:class:`TripItem`]
            Paginator that yields :class:`TripItem` instances.
        """
        return Paginator(
            lambda offset: self._export_trips(query, offset=offset),
            limit=limit,
        )

    async def _get_payments(self, transit_account_token: str, *, offset: int = 0) -> PaymentsPage:
        raw: PaymentsPageData = await self._http.get(
            f"/api/v1/Payments/{transit_account_token}", params={"offset": offset}
        )
        return PaymentsPage.from_dict(self, raw)

    def get_payments(
        self, transit_account_token: str, *, limit: int | None = None
    ) -> Paginator[Payment]:
        """Return a paginator over all payments for a transit account (card).

        Pagination is handled internally. Await the paginator to collect every
        payment into a list, or iterate with ``async for`` to stream page-by-page::

            payments = await client.get_payments(transit_account.xtat)
            async for payment in client.get_payments(transit_account.xtat):
                ...

        Parameters
        ----------
        transit_account_token: :class:`str`
            The XTAT token (:attr:`TransitAccount.xtat`) of the transit account.
        limit: :class:`int` or :data:`None`, optional
            Maximum number of payments to return. :data:`None` (default) returns all.

        Returns
        -------
        :class:`Paginator`[:class:`Payment`]
            Paginator that yields :class:`Payment` instances.
        """
        return Paginator(
            lambda offset: self._get_payments(transit_account_token, offset=offset), limit=limit
        )

    async def get_payment_receipt(self, token: str, id: str) -> PaymentReceipt:
        """Return the receipt for a single payment, including any related payments.

        Parameters
        ----------
        token: :class:`str`
            The back-office token (:attr:`Payment.xbot`) of the payment.
        id: :class:`str`
            The payment ID (:attr:`Payment.id`); the ``EVENT-...`` string, not a
            numeric trip ID.

        Returns
        -------
        :class:`PaymentReceipt`
            Receipt for the payment, including any related payments grouped under
            the same transaction.
        """
        raw: PaymentReceiptData = await self._http.get(
            f"/api/v1/Payments/receipt/{token}/{id}"
        )
        return PaymentReceipt.from_dict(self, raw)

    async def get_passenger_account(self) -> PassengerAccount:
        """Return basic account info for the authenticated user.

        Returns
        -------
        :class:`PassengerAccount`
            Authenticated user's passenger account, containing the registered
            email address.
        """
        raw: PassengerAccountData = await self._http.get("/api/v1/PassengerAccounts")
        return PassengerAccount.from_dict(raw)

    async def get_web_config(self) -> WebConfig:
        """Return the feature flags active for the authenticated account.

        Use ``config.is_enabled("FeatureName")`` to check individual flags.
        Covers authenticated-only features such as top-up, balance management,
        and account settings.

        Returns
        -------
        :class:`WebConfig`
            Feature flags for the authenticated account.
        """
        raw: WebConfigData = await self._http.get("/api/v1/WebConfig")
        return WebConfig.from_dict(raw)

    # ------------------------------------------------------------------
    # Anonymous endpoints — no bearer token required
    # ------------------------------------------------------------------

    async def get_version(self) -> ApiVersion:
        """Return the current OVpay API build version.

        Does not require authentication.

        Returns
        -------
        :class:`ApiVersion`
            Current build version, including major, minor, patch numbers and any
            pre-release tag.
        """
        raw: ApiVersionData = await self._http.get_anonymous("/api/Version")
        return ApiVersion.from_dict(raw)

    async def get_anonymous_config(self) -> AnonymousConfig:
        """Return public feature flags and document update keys.

        Does not require authentication. Covers public-facing flags such as
        ``WebLoginEnabled``, ``WebChatbotEnabled``, anonymous OV-card ordering,
        and top-up availability. Use ``config.is_enabled("FlagName")`` to check
        individual flags.

        Returns
        -------
        :class:`AnonymousConfig`
            Public feature flags and document update keys.
        """
        raw: AnonymousConfigData = await self._http.get_anonymous("/api/anonymous/V2/Config")
        return AnonymousConfig.from_dict(raw)

    async def get_faq_topics(self) -> list[FaqTopic]:
        """Return all FAQ topic categories.

        Does not require authentication. Pass :attr:`FaqTopic.id` to
        :meth:`get_faq_articles` to fetch the articles within a topic.

        Returns
        -------
        :class:`list`[:class:`FaqTopic`]
            All available FAQ topics.
        """
        raw: list[FaqTopicData] = await self._http.get_anonymous(
            "/api/anonymous/v1/faq/topics"
        )
        return [FaqTopic.from_dict(self, t) for t in raw]

    async def _get_faq_articles(
        self, topic_id: str, *, offset: int = 0
    ) -> FaqArticlesPage:
        raw: FaqArticlesPageData = await self._http.get_anonymous(
            "/api/anonymous/v1/faq/articles",
            params={"topicId": topic_id, "offset": offset},
        )
        return FaqArticlesPage.from_dict(self, raw)

    def get_faq_articles(
        self, topic_id: str, *, limit: int | None = None
    ) -> Paginator[FaqArticle]:
        """Return a paginator over all FAQ articles in a topic.

        Does not require authentication. Pagination is handled internally::

            articles = await client.get_faq_articles(topic_id)
            async for article in client.get_faq_articles(topic_id):
                ...

        Parameters
        ----------
        topic_id: :class:`str`
            The topic ID (:attr:`FaqTopic.id`) from :meth:`get_faq_topics`.
        limit: :class:`int` or :data:`None`, optional
            Maximum number of articles to return. :data:`None` (default) returns all.

        Returns
        -------
        :class:`Paginator`[:class:`FaqArticle`]
            Paginator that yields :class:`FaqArticle` instances.
        """
        return Paginator(
            lambda offset: self._get_faq_articles(topic_id, offset=offset),
            limit=limit,
        )

    async def _get_faq_topic_articles(
        self, topic_id: str | int, *, offset: int = 0
    ) -> FaqArticlesPage:
        raw: FaqArticlesPageData = await self._http.get_anonymous(
            f"/api/anonymous/v1/faq/topics/{topic_id}/articles",
            params={"offset": offset},
        )
        return FaqArticlesPage.from_dict(self, raw)

    def get_faq_topic_articles(
        self, topic_id: str | int, *, limit: int | None = None
    ) -> Paginator[FaqArticle]:
        """Return a paginator over all FAQ articles in a topic, via the topic path.

        Uses ``GET /api/anonymous/v1/faq/topics/{topic_id}/articles`` (as opposed
        to :meth:`get_faq_articles` which uses ``?topicId=`` as a query parameter).
        Does not require authentication.

        Parameters
        ----------
        topic_id: :class:`str` or :class:`int`
            The topic ID (:attr:`FaqTopic.id`) from :meth:`get_faq_topics`.
        limit: :class:`int` or :data:`None`, optional
            Maximum number of articles to return. :data:`None` (default) returns all.

        Returns
        -------
        :class:`Paginator`[:class:`FaqArticle`]
            Paginator that yields :class:`FaqArticle` instances.
        """
        return Paginator(
            lambda offset: self._get_faq_topic_articles(topic_id, offset=offset),
            limit=limit,
        )

    async def get_faq_article(self, article_id: str) -> FaqArticle:
        """Return a single FAQ article by ID, including its full HTML content.

        Does not require authentication.

        Parameters
        ----------
        article_id: :class:`str`
            The article ID (:attr:`FaqArticle.id`) from :meth:`get_faq_articles`.

        Returns
        -------
        :class:`FaqArticle`
            The requested FAQ article with full content populated.
        """
        raw: FaqArticleData = await self._http.get_anonymous(
            f"/api/anonymous/v1/faq/articles/{article_id}"
        )
        return FaqArticle.from_dict(self, raw)

    async def search(
        self, query: str, *, limit: int | None = None, language: str = "nl"
    ) -> SearchResponse:
        """Perform a full-text search across OVpay help content.

        Does not require authentication.

        Parameters
        ----------
        query: :class:`str`
            Search query string (e.g. ``"gemiste uitcheck"``).
        limit: :class:`int` or :data:`None`, optional
            Maximum number of results to return. :data:`None` (default) returns
            the server default.
        language: :class:`str`, optional
            BCP-47 language code for the results. Defaults to ``"nl"``.

        Returns
        -------
        :class:`SearchResponse`
            Search results containing matching articles and topics.
        """
        params: dict[str, str | int] = {
            "searchTerm": query,
            "lang": language,
        }
        if limit is not None:
            params["limit"] = limit
        raw: SearchResponseData = await self._http.get_anonymous(
            "/api/anonymous/v1/Search", params=params
        )
        return SearchResponse.from_dict(raw)

    async def get_search_suggestions(
        self, query: str, *, limit: int = 5, language: str = "nl"
    ) -> SearchSuggestions:
        """Return public search suggestions and matching FAQ articles.

        Does not require authentication.

        Parameters
        ----------
        query: :class:`str`
            Partial or full search query string.
        limit: :class:`int`, optional
            Maximum number of suggestions to return. Defaults to ``5``.
        language: :class:`str`, optional
            BCP-47 language code for the results. Defaults to ``"nl"``.

        Returns
        -------
        :class:`SearchSuggestions`
            Ranked search result suggestions and matching FAQ article stubs.
        """
        raw: SearchSuggestionsData = await self._http.get_anonymous(
            "/api/anonymous/v1/Search/suggestions",
            params={"searchTerm": query, "limit": limit, "lang": language},
        )
        return SearchSuggestions.from_dict(raw)

    async def get_faq_topic_by_name(self, name: str) -> FaqTopic:
        """Return an FAQ topic resolved by its public route slug.

        Does not require authentication.

        Parameters
        ----------
        name: :class:`str`
            The URL slug of the FAQ topic (e.g. ``"reizen-met-ovpay"``).

        Returns
        -------
        :class:`FaqTopic`
            The FAQ topic matching the given slug.
        """
        raw: FaqTopicData = await self._http.get_anonymous(
            f"/api/anonymous/v1/faq/topics/{name}"
        )
        return FaqTopic.from_dict(self, raw)

    async def get_ovpas_price(
        self, token_type: str, *, voucher_code: str | None = None
    ) -> OvPasPrice:
        """Return the current public OV-pas price for a given token type.

        Does not require authentication.

        Parameters
        ----------
        token_type: :class:`str`
            The token type to price (e.g. ``"OVChipCard"``).
        voucher_code: :class:`str` or :data:`None`, optional
            Optional voucher code to apply a discount. Defaults to :data:`None`.

        Returns
        -------
        :class:`OvPasPrice`
            Token price, full price, euro equivalent, and voucher status.
        """
        params: dict[str, Any] | None = {"voucherCode": voucher_code} if voucher_code else None
        raw: OvPasPriceData = await self._http.get_anonymous(
            f"/api/anonymous/v1/OvPas/token-type/{token_type}/price",
            params=params,
        )
        return OvPasPrice.from_dict(raw)

    async def get_transaction(
        self, order_id: str, *, transaction_reason: str | None = None
    ) -> dict[str, object]:
        """Return the status and details of an authenticated transaction.

        Parameters
        ----------
        order_id: :class:`str`
            The order ID of the transaction to look up.
        transaction_reason: :class:`str` or :data:`None`, optional
            Optional reason code to filter by. Defaults to :data:`None`.

        Returns
        -------
        :class:`dict`
            Raw transaction response from the API.
        """
        params: dict[str, Any] | None = (
            {"transactionReason": transaction_reason}
            if transaction_reason is not None
            else None
        )
        raw: dict[str, object] = await self._http.get(
            f"/api/v3/Transactions/{order_id}", params=params
        )
        return raw

    async def export_trips_pdf(
        self,
        from_date: date | datetime | str,
        to_date: date | datetime | str,
        query: ExportQuery | None = None,
    ) -> bytes:
        """Download an OVpay trip-export as a PDF.

        Uses ``POST /api/v2/TripExport/download``. The same
        :class:`ExportQuery` filters apply. Pass a pre-built *query* to
        use filters; pass *from_date* / *to_date* for a plain date-range export.
        If *query* is given, *from_date* and *to_date* are ignored.

        Parameters
        ----------
        from_date: :class:`date` or :class:`datetime` or :class:`str`
            Start of the date range (ignored when *query* is provided).
        to_date: :class:`date` or :class:`datetime` or :class:`str`
            End of the date range (ignored when *query* is provided).
        query: :class:`ExportQuery` or :data:`None`, optional
            Pre-built query with filters. When :data:`None` a plain date-range
            query is constructed from *from_date* / *to_date*.

        Returns
        -------
        :class:`bytes`
            Raw PDF bytes, ready to write to a file or serve over HTTP.
        """
        if query is None:
            query = ExportQuery(from_date, to_date)
        return await self._download_export("/api/v2/TripExport/download", query)

    async def export_trips_csv(
        self,
        from_date: date | datetime | str,
        to_date: date | datetime | str,
        query: ExportQuery | None = None,
    ) -> bytes:
        """Download an OVpay trip-export as a CSV.

        Uses ``POST /api/v2/TripExport/download/csv``. The same
        :class:`ExportQuery` filters apply. Pass a pre-built *query* to
        use filters; pass *from_date* / *to_date* for a plain date-range export.
        If *query* is given, *from_date* and *to_date* are ignored.

        Parameters
        ----------
        from_date: :class:`date` or :class:`datetime` or :class:`str`
            Start of the date range (ignored when *query* is provided).
        to_date: :class:`date` or :class:`datetime` or :class:`str`
            End of the date range (ignored when *query* is provided).
        query: :class:`ExportQuery` or :data:`None`, optional
            Pre-built query with filters. When :data:`None` a plain date-range
            query is constructed from *from_date* / *to_date*.

        Returns
        -------
        :class:`bytes`
            Raw CSV bytes, ready to write to a file or decode as UTF-8.
        """
        if query is None:
            query = ExportQuery(from_date, to_date)
        return await self._download_export("/api/v2/TripExport/download/csv", query)

    async def _download_export(self, path: str, query: ExportQuery) -> bytes:
        token = await self._http._auth.get_token()
        url = f"{self._http.base_url}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Referer": "https://www.ovpay.nl/",
        }
        async with self._http._require_session().post(
            url, headers=headers, json=query._to_body()
        ) as response:
            response.raise_for_status()
            return await response.read()

    async def get_photo_upload_status(self, reference_id: str) -> str:
        """Return the processing status of a previously uploaded photo.

        The endpoint returns a plain-text status string such as ``"pending"``,
        ``"processing"``, or ``"done"``.

        Parameters
        ----------
        reference_id: :class:`str`
            The reference ID returned when the photo was uploaded.

        Returns
        -------
        :class:`str`
            Current processing status of the uploaded photo.
        """
        token = await self._http._auth.get_token()
        url = f"{self._http.base_url}/api/v1/Photo/upload-status/{reference_id}"
        async with self._http._require_session().get(
            url, headers={"Authorization": f"Bearer {token}"}
        ) as response:
            response.raise_for_status()
            return await response.text()

    async def lookup_address_anonymously(
        self, postal_code: str, house_number: str
    ) -> Address:
        """Resolve a Dutch postal code and house number to a full address.

        Does not require authentication. Use :meth:`lookup_address` for the
        authenticated variant, which may return additional fields.

        Parameters
        ----------
        postal_code: :class:`str`
            Dutch postal code, e.g. ``"1234 AB"``.
        house_number: :class:`str`
            House number, e.g. ``"10"``.

        Returns
        -------
        :class:`Address`
            Full address for the given postal code and house number.
        """
        raw: AddressData = await self._http.get_anonymous(
            "/api/anonymous/v1/LookupAddress",
            params={"postalCode": postal_code, "houseNumber": house_number},
        )
        return Address.from_dict(raw)

    async def get_customer(self) -> Customer:
        """Return personal profile data for the authenticated user.

        Contains name, email, address, phone number, and ARL contracts.
        Fields may be :data:`None` for accounts with an incomplete profile.

        Returns
        -------
        :class:`Customer`
            Profile data for the authenticated user.
        """
        raw: CustomerData = await self._http.get("/api/v1/Customers")
        return Customer.from_dict(raw)

    async def lookup_address(self, postal_code: str, house_number: str) -> Address:
        """Resolve a Dutch postal code and house number to a full address.

        Parameters
        ----------
        postal_code: :class:`str`
            Dutch postal code, e.g. ``"1234 AB"``.
        house_number: :class:`str`
            House number, e.g. ``"10"``.

        Returns
        -------
        :class:`Address`
            Full address for the given postal code and house number.
        """
        raw: AddressData = await self._http.get(
            "/api/v1/LookupAddress",
            params={"postalCode": postal_code, "houseNumber": house_number},
        )
        return Address.from_dict(raw)
