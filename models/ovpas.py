from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from internals._types import OvPasPriceData

__all__ = ("OvPasPrice",)


@dataclass
class OvPasPrice:
    """OV-pas pricing from GET /api/anonymous/v1/OvPas/token-type/{token_type}/price."""

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
