from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from client import OVPayClient
    from internals._types import (
        CardProductsData,
        PersonalAccountDataDict,
        PersonalizationData,
        TransitAccountData,
    )
    from internals.pagination import Paginator
    from poller import Payment

    from .trip import TripItem

__all__ = (
    "PersonalAccountData",
    "Personalization",
    "TransitAccount",
    "TransitAccountProducts",
)


@dataclass
class Personalization:
    order: int
    name: str
    color: str
    medium: str | None

    @classmethod
    def from_dict(cls, d: PersonalizationData) -> Personalization:
        return cls(
            order=d["order"], name=d["name"], color=d["color"], medium=d.get("medium")
        )


@dataclass
class PersonalAccountData:
    is_available: bool
    is_tagged: bool

    @classmethod
    def from_dict(cls, d: PersonalAccountDataDict) -> PersonalAccountData:
        return cls(is_available=d["isAvailable"], is_tagged=d["isTagged"])


@dataclass
class TransitAccount:
    """An OVpay transit account — displayed in the UI as a card (pas/betaalmiddel)."""

    _client: OVPayClient

    xtat: str | None  # None when returned as the `token` field inside TripDetails
    xbot: str
    status: str
    medium_type: str
    card_number: str | None
    card_sequence_number: str | None
    expiration_date: datetime | None
    balance: int | None
    personalization: Personalization | None
    personal_account_data: PersonalAccountData | None
    has_open_trip: bool
    has_full_post_paid: bool
    arl_status: str | None
    is_provisional: bool | None

    @property
    def balance_euros(self) -> float | None:
        """:class:`float` | :data:`None`: Returns the balance in euros, or ``None`` if the balance is not available."""
        return self.balance / 100 if self.balance is not None else None

    @property
    def name(self) -> str | None:
        """:class:`str` | :data:`None`: Returns the name of the card, or ``None`` if the card is not personalized.

        This is an alias for :attr:`personalization.name`.
        """
        return self.personalization.name if self.personalization else None

    @property
    def color(self) -> str | None:
        """:class:`str` | :data:`None`: Returns the color of the card, or ``None`` if the card is not personalized.

        This is an alias for :attr:`personalization.color`.
        """
        return self.personalization.color if self.personalization else None

    @property
    def medium(self) -> str | None:
        """:class:`str` | :data:`None`: Returns the medium of the card, or ``None`` if the card is not personalized.

        This is an alias for :attr:`personalization.medium`.
        """
        return self.personalization.medium if self.personalization else None

    @property
    def order(self) -> int | None:
        """:class:`int` | :data:`None`: Returns the order of the card in the list of personalized cards,
        or ``None`` if the card is not personalized.

        This is an alias for :attr:`personalization.order`.
        """
        return self.personalization.order if self.personalization else None

    @property
    def is_available(self) -> bool | None:
        """:class:`bool` | :data:`None`: Returns whether the card is available for use,
        or ``None`` if the personal account data is not available.

        This is an alias for :attr:`personal_account_data.is_available`.
        """
        return (
            self.personal_account_data.is_available
            if self.personal_account_data
            else None
        )

    @property
    def is_tagged(self) -> bool | None:
        """:class:`bool` | :data:`None`: Returns whether the card is tagged, or ``None`` if the
        personal account data is not available.

        This is an alias for :attr:`personal_account_data.is_tagged`.
        """
        return (
            self.personal_account_data.is_tagged if self.personal_account_data else None
        )

    @property
    def external_transit_account_token(self) -> str | None:
        """:class:`str` | :data:`None`: Returns the external transit account token (xtat) for this card.

        This is an alias for :attr:`xtat`.
        """
        return self.xtat

    @property
    def external_back_office_token(self) -> str:
        """:class:`str`: Returns the external back office token (xbot) for this card.

        This is an alias for :attr:`xbot`.
        """
        return self.xbot

    @property
    def account_token(self) -> str | None:
        """:class:`str` | :data:`None`: Returns the external transit account token (xtat) for this card.

        This is an alias for :attr:`xtat`.
        """
        return self.xtat

    @property
    def back_office_token(self) -> str:
        """:class:`str`: Returns the external back office token (xbot) for this card.

        This is an alias for :attr:`xbot`.
        """
        return self.xbot

    @classmethod
    def from_dict(cls, client: OVPayClient, d: TransitAccountData) -> TransitAccount:
        exp = d.get("expirationDate")
        p = d.get("personalization")
        pad = d.get("personalAccountData")
        return cls(
            _client=client,
            xtat=d.get("xtat"),
            xbot=d["xbot"],
            status=d.get("status", ""),
            medium_type=d.get("mediumType", ""),
            card_number=d.get("cardNumber"),
            card_sequence_number=d.get("cardSequenceNumber"),
            expiration_date=datetime.fromisoformat(exp) if exp else None,
            balance=d.get("balance"),
            personalization=Personalization.from_dict(p) if p else None,
            personal_account_data=PersonalAccountData.from_dict(pad) if pad else None,
            has_open_trip=d.get("hasOpenTrip", False),
            has_full_post_paid=d.get("hasFullPostPaid", False),
            arl_status=d.get("arlStatus"),
            is_provisional=d.get("isProvisional"),
        )

    async def get_personalization(self) -> Personalization | None:
        """Fetch and return the latest personalization data for this card.

        The card instance is updated in place so the :attr:`name`, :attr:`color`,
        :attr:`medium`, and :attr:`order` convenience properties also reflect
        the refreshed data.
        """
        cards = await self._client.get_transit_accounts(with_personalization=True)
        card = next(
            (
                card
                for card in cards
                if (self.xtat and card.xtat == self.xtat) or card.xbot == self.xbot
            ),
            None,
        )
        if card is None:
            return None

        self.personalization = card.personalization
        return self.personalization

    async def get_details(self) -> TransitAccount:
        """Fetch the latest complete details for this card."""
        if not self.xtat:
            raise ValueError("TransitAccount.xtat is None. Cannot fetch card details.")
        return await self._client.get_transit_account(self.xtat)

    async def get_token_details(self) -> TransitAccount:
        """Fetch this card through its back-office token."""
        return await self._client.get_token_details(self.xbot)

    async def get_products(self) -> TransitAccountProducts:
        """Fetch products and age-discount information associated with this card."""
        if not self.xtat:
            raise ValueError("TransitAccount.xtat is None. Cannot fetch card products.")
        return await self._client.get_transit_account_products(self.xtat)

    async def get_personal_account_data(self) -> PersonalAccountData | None:
        """Fetch and return the latest personal-account data for this card."""
        cards = await self._client.get_transit_accounts(with_personalization=True)
        card = next(
            (
                card
                for card in cards
                if (self.xtat and card.xtat == self.xtat) or card.xbot == self.xbot
            ),
            None,
        )
        if card is None:
            return None

        self.personal_account_data = card.personal_account_data
        return self.personal_account_data

    def get_trips(self, limit: int | None = None) -> Paginator[TripItem]:
        """Returns a paginator over every trip for this card.

        Trips can be collected into a list, or iterated with ``async for`` to stream
        them page-by-page::

            trips = await card.get_trips()
            async for trip in card.get_trips():
                ...

        Parameters
        ----------
        limit: int | None
            Maximum number of trips to return. ``None`` returns all.
        """
        if not self.xtat:
            raise ValueError(
                "TransitAccount.xtat is None. Cannot fetch trips for this card."
            )
        return self._client.get_trips(self.xtat, limit=limit)

    def export_trips(
        self,
        from_date: datetime | str,
        to_date: datetime | str,
        limit: int | None = None,
    ) -> Paginator[TripItem]:
        """Returns a paginator over every trip for this card, via the Trip Export API.

        Trips can be collected into a list, or iterated with ``async for`` to stream
        them page-by-page::

            trips = await card.export_trips()
            async for trip in card.export_trips():
                ...

        Parameters
        ----------
        from_date: datetime | str | None
            Range start, as an ISO string, ``date``, or ``datetime``.
        to_date: datetime | str | None
            Range end, as an ISO string, ``date``, or ``datetime``.
        limit: int | None
            Maximum number of trips to return. ``None`` returns all.
        """
        if not self.xtat:
            raise ValueError(
                "TransitAccount.xtat is None. Cannot export trips for this card."
            )
        return self._client.export_trips(self.xtat, from_date, to_date, limit=limit)

    def get_payments(self, limit: int | None = None) -> Paginator[Payment]:
        """Returns a paginator over every payment for this transit card.

        Payments can be collected into a list, or iterated with ``async for`` to stream
        them page-by-page::

            payments = await card.get_payments()
            async for payment in card.get_payments():
                ...

        Parameters
        ----------
        limit: int | None
            Maximum number of payments to return. ``None`` returns all.
        """
        if not self.xtat:
            raise ValueError(
                "TransitAccount.xtat is None. Cannot fetch payments for this card."
            )
        return self._client.get_payments(self.xtat, limit=limit)


@dataclass
class TransitAccountProducts:
    """Products and age-discount profile from GET /api/v2/Products/{xtat}."""

    products: list[dict[str, object]]
    age_discount_profile: dict[str, object] | None

    @classmethod
    def from_dict(cls, d: CardProductsData) -> TransitAccountProducts:
        return cls(
            products=list(d.get("products", [])),
            age_discount_profile=d.get("ageDiscountProfile"),
        )
