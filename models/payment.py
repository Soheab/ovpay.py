from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import OVPayClient
    from ..internals._types import PaymentData, PaymentReceiptData, PaymentsPageData

__all__ = ("Payment", "PaymentReceipt", "PaymentsPage")


@dataclass
class Payment:
    """Represents a single payment associated with a transit card.

    Attributes
    ----------
    service_reference_id: :class:`str`
        Internal service reference identifier for this payment.
    xbot: :class:`str`
        The external back-office token. Pass this together with :attr:`id`
        to :meth:`get_payment_receipt`.
    id: :class:`str`
        The payment event id.
    status: :class:`str`
        The payment status, e.g. ``"Settled"`` or ``"Rejected"``.
    transaction_timestamp: :class:`datetime.datetime`
        When the transaction occurred.
    transaction_type: :class:`str`
        The type of transaction, e.g. ``"CheckIn"`` or ``"CheckOut"``.
    amount: :class:`int`
        The transaction amount in euro-cents. Negative means a debit.
        Use :attr:`amount_euros` for the float equivalent.
    amount_due: :class:`int`
        The amount due in euro-cents. Use :attr:`amount_due_euros` for the float equivalent.
    currency: :class:`str`
        The currency code, e.g. ``"EUR"``.
    payment_method: :class:`str`
        The payment method used, e.g. ``"Creditcard"`` or ``"OVChipkaart"``.
    rejection_reason: :class:`str` | :data:`None`
        The reason the payment was rejected, or ``None`` if it wasn't.
    loyalty_or_discount: :class:`bool`
        Whether a loyalty or discount was applied to this payment.
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
    """Represents a paginated list of payments.

    Attributes
    ----------
    offset: :class:`int`
        The index of the first item in this page.
    batch_size: :class:`int`
        How many items were requested per page.
    end_of_list_reached: :class:`bool`
        ``True`` when there are no more pages after this one.
    items: :class:`list`[:class:`Payment`]
        The payments in this page.
    """

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
    """Represents a payment receipt.

    Attributes
    ----------
    related_payments: :class:`list`[:class:`Payment`]
        All payments tied to this receipt, including any corrections.
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
