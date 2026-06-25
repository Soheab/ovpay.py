from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from client import OVPayClient
    from internals._types import PaymentData, PaymentReceiptData, PaymentsPageData

__all__ = ("Payment", "PaymentReceipt", "PaymentsPage")


@dataclass
class Payment:
    """A single payment / transaction associated with a card.

    Returned by GET /api/v1/Payments/{xtat}.
    amount / amount_due are in euro-cents (negative = debit).
    Use amount_euros / amount_due_euros for floats.

    id: the payment event id — pass to get_payment_receipt() together with xbot.
    xbot: the back-office token — pass to get_payment_receipt().
    """

    _client: OVPayClient
    service_reference_id: str
    xbot: str
    id: str
    status: str
    transaction_timestamp: datetime
    transaction_type: str
    amount: int
    amount_due: int
    currency: str
    payment_method: str
    rejection_reason: str | None
    loyalty_or_discount: bool

    @property
    def amount_euros(self) -> float:
        return self.amount / 100

    @property
    def amount_due_euros(self) -> float:
        return self.amount_due / 100

    @property
    def external_back_office_token(self) -> str:
        """:class:`str`: The external back-office token for this payment."""
        return self.xbot

    @property
    def token(self) -> str:
        """:class:`str`: The external back-office token for this payment."""
        return self.xbot

    @classmethod
    def from_dict(cls, client: OVPayClient, d: PaymentData) -> Payment:
        return cls(
            _client=client,
            service_reference_id=d["serviceReferenceId"],
            xbot=d["xbot"],
            id=d["id"],
            status=d["status"],
            transaction_timestamp=datetime.fromisoformat(d["transactionTimestamp"]),
            transaction_type=d["transactionType"],
            amount=d["amount"],
            amount_due=d["amountDue"],
            currency=d["currency"],
            payment_method=d["paymentMethod"],
            rejection_reason=d.get("rejectionReason"),
            loyalty_or_discount=d.get("loyaltyOrDiscount", False),
        )

    async def get_payment_receipt(self) -> PaymentReceipt:
        """Fetches the payment receipt for this payment.

        Returns
        -------
        PaymentReceipt
            The payment receipt for this payment.
        """
        return await self._client.get_payment_receipt(self.xbot, self.id)


@dataclass
class PaymentsPage:
    """Paginated payments response from GET /api/v1/Payments/{xtat}."""

    _client: OVPayClient
    offset: int
    batch_size: int
    end_of_list_reached: bool
    items: list[Payment] = field(default_factory=list[Payment])

    @classmethod
    def from_dict(cls, client: OVPayClient, d: PaymentsPageData) -> PaymentsPage:
        return cls(
            _client=client,
            offset=d.get("offset", 0),
            batch_size=d.get("batchSize", 0),
            end_of_list_reached=d.get("endOfListReached", False),
            items=[Payment.from_dict(client, p) for p in d.get("items", [])],
        )


@dataclass
class PaymentReceipt:
    """Receipt from GET /api/v1/Payments/receipt/{xbot}/{payment_id}.

    Contains the payment plus any related payments (e.g. corrections).
    """

    _client: OVPayClient
    related_payments: list[Payment]

    @classmethod
    def from_dict(cls, client: OVPayClient, d: PaymentReceiptData) -> PaymentReceipt:
        return cls(
            _client=client,
            related_payments=[
                Payment.from_dict(client, p) for p in d.get("relatedPayments", [])
            ],
        )
