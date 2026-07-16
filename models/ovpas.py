from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..internals._types import OvPasPriceData

__all__ = ("OvPasPrice",)


@dataclass
class OvPasPrice:
    """Represents the price for an OV-pas token type.

    Attributes
    ----------
    token_price: :class:`int`
        The price to pay in euro-cents, after any voucher discount.
    full_token_price: :class:`int`
        The undiscounted price in euro-cents.
    token_price_euros: :class:`float`
        The price to pay in euros, as returned directly by the API.
    voucher_status: :class:`str` | :data:`None`
        The status of an applied voucher, or ``None`` if no voucher was used.
    voucher_discount_amount: :class:`int` | :data:`None`
        The discount amount in euro-cents granted by the voucher.
    voucher_discount_type: :class:`str` | :data:`None`
        How the discount is applied, e.g. ``"Amount"`` or ``"Percentage"``.
    """

    token_price: int
    full_token_price: int
    token_price_euros: float
    voucher_status: str | None
    voucher_discount_amount: int | None
    voucher_discount_type: str | None

    @property
    def token_price_euros_float(self) -> float:
        """:class:`float`: Token price in euros."""
        return self.token_price / 100

    @classmethod
    def from_dict(cls, d: OvPasPriceData) -> OvPasPrice:
        return cls(
            token_price=d["tokenPrice"],
            full_token_price=d["fullTokenPrice"],
            token_price_euros=float(d["tokenPriceInEuros"]),
            voucher_status=d.get("voucherStatus"),
            voucher_discount_amount=d.get("voucherDiscountAmount"),
            voucher_discount_type=d.get("voucherDiscountType"),
        )
