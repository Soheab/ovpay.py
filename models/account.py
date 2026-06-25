from __future__ import annotations

from dataclasses import dataclass
import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from internals._types import (
        AddressData,
        CustomerAddressData,
        CustomerData,
        PassengerAccountData,
    )

__all__ = (
    "Address",
    "Customer",
    "CustomerAddress",
    "PassengerAccount",
)


@dataclass
class CustomerAddress:
    """Represents a customer address.

    Attributes
    ----------
    street: :class:`str` | :data:`None`
        The street name of the address.
    house_number: :class:`str` | :data:`None`
        The house number of the address.
    house_number_addition: :class:`str` | :data:`None`
        The house number addition of the address.
    postal_code: :class:`str` | :data:`None`
        The postal code of the address.
    city: :class:`str` | :data:`None`
        The city of the address.
    country: :class:`str` | :data:`None`
        The country of the address.
    """

    street: str | None
    house_number: str | None
    house_number_addition: str | None
    postal_code: str | None
    city: str | None
    country: str | None

    @classmethod
    def from_dict(cls, d: CustomerAddressData) -> CustomerAddress:
        return cls(
            street=d.get("street"),
            house_number=d.get("houseNumber"),
            house_number_addition=d.get("houseNumberAddition"),
            postal_code=d.get("postalCode"),
            city=d.get("city"),
            country=d.get("country"),
        )

    def __repr__(self) -> str:
        return f"{self.street} {self.house_number}{self.house_number_addition or ''}, {self.postal_code} {self.city}, {self.country}"


@dataclass
class Customer:
    """Represents a customer.

    Contains personal details (name, email, address) for the authenticated user.
    Fields may be null if the account was registered without full profile data.

    Attributes
    ----------
    initials: :class:`str` | :data:`None`
        The initials of the customer.
    prefix: :class:`str` | :data:`None`
        The prefix of the customer's last name (e.g. "van", "de").
    last_name: :class:`str` | :data:`None`
        The last name of the customer.
    email: :class:`str` | :data:`None`
        The email address of the customer.
    birth_date: :class:`datetime.date` | :data:`None`
        The birth date of the customer.
    phone_number: :class:`str` | :data:`None`
        The phone number of the customer.
    address: :class:`CustomerAddress` | :data:`None`
        The address of the customer.
    arl_contracts: :class:`list`[:class:`object`] | :data:`None`
        The ARL contracts of the customer. The structure of these objects is
        not known.
    """

    initials: str | None
    prefix: str | None
    last_name: str | None
    email: str | None
    birth_date: datetime.date | None
    phone_number: str | None
    address: CustomerAddress | None
    arl_contracts: list[object] | None

    @classmethod
    def from_dict(cls, d: CustomerData) -> Customer:
        addr = d.get("address")
        return cls(
            initials=d.get("initials"),
            prefix=d.get("prefix"),
            last_name=d.get("lastName"),
            email=d.get("email"),
            birth_date=datetime.date.fromisoformat(bd)
            if (bd := d.get("birthDate"))
            else None,
            phone_number=d.get("phoneNumber"),
            address=CustomerAddress.from_dict(addr) if addr else None,
            arl_contracts=d.get("arlContracts"),
        )


@dataclass
class Address:
    """Represents a generic address.

    Attributes
    ----------
    street: :class:`str` | :data:`None`
        The street name.
    house_number: :class:`str` | :data:`None`
        The house number.
    house_number_addition: :class:`str` | :data:`None`
        The house number addition.
    postal_code: :class:`str` | :data:`None`
        The postal code.
    city: :class:`str` | :data:`None`
        The city.
    country: :class:`str` | :data:`None`
        The country.
    """

    street: str | None
    house_number: str | None
    house_number_addition: str | None
    postal_code: str | None
    city: str | None
    country: str | None

    @classmethod
    def from_dict(cls, d: AddressData) -> Address:
        return cls(
            street=d.get("street"),
            house_number=d.get("houseNumber"),
            house_number_addition=d.get("houseNumberAddition"),
            postal_code=d.get("postalCode"),
            city=d.get("city"),
            country=d.get("country"),
        )

    def __repr__(self) -> str:
        return f"{self.street} {self.house_number}{self.house_number_addition or ''}, {self.postal_code} {self.city}, {self.country}"


@dataclass
class PassengerAccount:
    """Represents a passenger account.

    Attributes
    ----------
    email: :class:`str`
        The email address of the passenger account.
    """

    email: str

    @classmethod
    def from_dict(cls, d: PassengerAccountData) -> PassengerAccount:
        return cls(email=d["email"])
