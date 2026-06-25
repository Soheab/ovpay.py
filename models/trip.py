from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from .transit_account import TransitAccount

if TYPE_CHECKING:
    from client import OVPayClient
    from internals._types import TripData, TripDetailsData, TripItemData, TripsPageData


__all__ = ("Location", "Trip", "TripDetails", "TripItem", "TripsPage")


@dataclass
class Location:
    name: str
    city: str | None = None
    country: str | None = None

    @classmethod
    def from_value(cls, v: str | dict[str, str | None] | None) -> Location | None:
        if v is None:
            return None
        if isinstance(v, str):
            return cls(name=v)
        return cls(
            name=v.get("name") or "",
            city=v.get("city"),
            country=v.get("country"),
        )


@dataclass
class Trip:
    _client: OVPayClient

    xbot: str
    id: int
    version: int
    transport: str
    status: str
    check_in_location: Location | None
    check_in_timestamp: datetime | None
    check_out_location: Location | None
    check_out_timestamp: datetime | None
    currency: str | None
    fare: int | None
    organisation_name: str | None
    fare_nature: str | None
    payment_method_name: str | None
    sales_product_commercial_name: str | None

    @property
    def fare_euros(self) -> float | None:
        return self.fare / 100 if self.fare is not None else None

    @property
    def external_back_office_token(self) -> str:
        """:class:`str`: The external back-office token for this trip."""
        return self.xbot

    @property
    def token(self) -> str:
        """:class:`str`: The external back-office token for this trip."""
        return self.xbot

    @classmethod
    def from_dict(cls, client: OVPayClient, d: TripData) -> Trip:
        def _dt(v: str | None) -> datetime | None:
            return datetime.fromisoformat(v) if v else None

        return cls(
            _client=client,
            xbot=d["xbot"],
            id=d["id"],
            version=d.get("version", 1),
            transport=d.get("transport", ""),
            status=d.get("status", ""),
            check_in_location=Location.from_value(d.get("checkInLocation")),
            check_in_timestamp=_dt(d.get("checkInTimestamp")),
            check_out_location=Location.from_value(d.get("checkOutLocation")),
            check_out_timestamp=_dt(d.get("checkOutTimestamp")),
            currency=d.get("currency"),
            fare=d.get("fare"),
            organisation_name=d.get("organisationName"),
            fare_nature=d.get("fareNature"),
            payment_method_name=d.get("paymentMethodName"),
            sales_product_commercial_name=d.get("salesProductCommercialName"),
        )

    async def get_details(self) -> TripDetails:
        """Fetch the full details for this trip."""
        return await self._client.get_trip_details(self.xbot, self.id)


@dataclass
class TripItem:
    """One row in a trips page — the trip plus correction/discount metadata."""

    trip: Trip
    corrected_from: None
    corrected_from_type: None
    supersedes_fare: None
    age_discounts: list[object]
    product_discounts: list[object]
    day_capping: None
    post_paid_payment_information: None

    @classmethod
    def from_dict(cls, client: OVPayClient, d: TripItemData) -> TripItem:
        return cls(
            trip=Trip.from_dict(client, d["trip"]),
            corrected_from=d.get("correctedFrom"),
            corrected_from_type=d.get("correctedFromType"),
            supersedes_fare=d.get("supersedesFare"),
            age_discounts=list(d.get("ageDiscounts") or []),
            product_discounts=list(d.get("productDiscounts") or []),
            day_capping=d.get("dayCapping"),
            post_paid_payment_information=d.get("postPaidPaymentInformation"),
        )

    async def get_details(self) -> TripDetails:
        """Fetch the full details for this trip item."""
        return await self.trip.get_details()


@dataclass
class TripsPage:
    """Paginated trips response from GET /api/v3/Trips/{xtat}."""

    _client: OVPayClient
    offset: int
    batch_size: int
    end_of_list_reached: bool
    items: list[TripItem] = field(default_factory=list[TripItem])

    @classmethod
    def from_dict(cls, client: OVPayClient, d: TripsPageData) -> TripsPage:
        return cls(
            _client=client,
            offset=d.get("offset", 0),
            batch_size=d.get("batchSize", 0),
            end_of_list_reached=d.get("endOfListReached", False),
            items=[TripItem.from_dict(client, i) for i in d.get("items", [])],
        )


@dataclass
class TripDetails:
    """Full trip detail from GET /api/v3/Trips/{xbot}/{trip_id}."""

    _client: OVPayClient
    trip: Trip
    card: TransitAccount | None
    correction_options: None
    corrected_from: None
    corrected_from_type: None
    supersedes_fare: None
    age_discounts: list[object]
    product_discounts: list[object]
    day_capping: None
    post_paid_payment_information: None

    @classmethod
    def from_dict(cls, client: OVPayClient, d: TripDetailsData) -> TripDetails:
        return cls(
            _client=client,
            trip=Trip.from_dict(client, d["trip"]),
            card=TransitAccount.from_dict(client, d["token"]) if d.get("token") else None,
            correction_options=d.get("correctionOptions"),
            corrected_from=d.get("correctedFrom"),
            corrected_from_type=d.get("correctedFromType"),
            supersedes_fare=d.get("supersedesFare"),
            age_discounts=list(d.get("ageDiscounts") or []),
            product_discounts=list(d.get("productDiscounts") or []),
            day_capping=d.get("dayCapping"),
            post_paid_payment_information=d.get("postPaidPaymentInformation"),
        )
