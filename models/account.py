from __future__ import annotations

from dataclasses import dataclass
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


@dataclass
class Customer:
    """Customer profile from GET /api/v1/Customers.

    Contains personal details (name, email, address) for the authenticated user.
    Fields may be null if the account was registered without full profile data.
    """

    initials: str | None
    prefix: str | None
    last_name: str | None
    email: str | None
    birth_date: str | None
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
            birth_date=d.get("birthDate"),
            phone_number=d.get("phoneNumber"),
            address=CustomerAddress.from_dict(addr) if addr else None,
            arl_contracts=d.get("arlContracts"),
        )


@dataclass
class Address:
    """A resolved address from GET /api/v1/LookupAddress."""

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


@dataclass
class PassengerAccount:
    """Basic account info from GET /api/v1/PassengerAccounts."""

    email: str

    @classmethod
    def from_dict(cls, d: PassengerAccountData) -> PassengerAccount:
        return cls(email=d["email"])
