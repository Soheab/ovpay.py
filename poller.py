from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from .models import Payment, TransitAccount, TripItem

if TYPE_CHECKING:
    from .client import OVPayClient

log = logging.getLogger(__name__)

# Callback type aliases
_TripCB = Callable[[TripItem], Coroutine[Any, Any, None]]
_PaymentCB = Callable[[Payment], Coroutine[Any, Any, None]]
_BalanceCB = Callable[[TransitAccount, int, int], Coroutine[Any, Any, None]]


class OVPayPoller:
    """Polls OVpay endpoints on a fixed interval and fires async callbacks on changes.

    Tracked events
    --------------
    - new_trip:        a TripItem that wasn't present in the previous poll
    - new_payment:     a Payment that wasn't present in the previous poll
    - balance_changed: a TransitAccount whose balance changed between polls

    Usage
    -----
        async with OVPayClient(cookie=cookie) as client:
            poller = OVPayPoller(client, interval=60)

            @poller.on_new_trip
            async def on_trip(trip: TripItem) -> None:
                print(trip.trip.fare_euros)

            @poller.on_balance_changed
            async def on_balance(card: TransitAccount, old: int, new: int) -> None:
                print(f"{card.name}: {old/100:.2f} → {new/100:.2f}")

            await poller.start()   # runs until cancelled

    The poller fetches all cards on every cycle, then for each card
    fetches all trips and payments. stop() cancels the background task cleanly.
    """

    def __init__(self, client: OVPayClient, *, interval: float = 60.0) -> None:
        self._client = client
        self._interval = interval

        self._trip_cbs: list[_TripCB] = []
        self._payment_cbs: list[_PaymentCB] = []
        self._balance_cbs: list[_BalanceCB] = []

        # State keyed by xtat
        self._seen_trip_ids: dict[str, set[int]] = {}
        self._seen_payment_ids: dict[str, set[str]] = {}
        self._last_balances: dict[str, int] = {}

        self._task: asyncio.Task[None] | None = None

    @property
    def interval(self) -> float:
        """:class:`float`: The polling interval in seconds."""
        return self._interval

    @interval.setter
    def interval(self, value: float) -> None:
        if value <= 0:
            raise ValueError("Interval must be positive")
        self._interval = value

    # ------------------------------------------------------------------
    # Decorator registration
    # ------------------------------------------------------------------

    def on_new_trip(self, fn: _TripCB) -> _TripCB:
        """Register a callback fired for each new TripItem discovered."""
        self._trip_cbs.append(fn)
        return fn

    def on_new_payment(self, fn: _PaymentCB) -> _PaymentCB:
        """Register a callback fired for each new Payment discovered."""
        self._payment_cbs.append(fn)
        return fn

    def on_balance_changed(self, fn: _BalanceCB) -> _BalanceCB:
        """Register a callback fired when a card's balance changes.

        Signature: async def cb(card: TransitAccount, old_cents: int, new_cents: int)
        """
        self._balance_cbs.append(fn)
        return fn

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Run the polling loop until cancelled or stop() is called.

        Performs an initial seeding poll (no callbacks fired) then fires
        callbacks only for changes detected in subsequent polls.
        """
        await self._seed()
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        """Cancel the background polling task."""
        if self._task and not self._task.done():
            self._task.cancel()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _seed(self) -> None:
        """First poll — populate seen sets without firing any callbacks."""
        cards = await self._client.get_transit_accounts()
        for card in cards:
            if not card.xtat:
                continue
            xtat = card.xtat

            if card.balance is not None:
                self._last_balances[xtat] = card.balance

            trips = await self._client.get_trips(xtat)
            self._seen_trip_ids[xtat] = {item.trip.id for item in trips}

            payments = await self._client.get_payments(xtat)
            self._seen_payment_ids[xtat] = {p.id for p in payments}

        log.debug(
            "Poller seeded: %d cards, %d trips, %d payments",
            len(cards),
            sum(len(v) for v in self._seen_trip_ids.values()),
            sum(len(v) for v in self._seen_payment_ids.values()),
        )

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self._poll()
            except Exception:
                log.exception("Poller error — will retry on next interval")

    async def _poll(self) -> None:
        cards = await self._client.get_transit_accounts()
        for card in cards:
            if not card.xtat:
                continue
            xtat = card.xtat

            # Balance change
            if card.balance is not None and xtat in self._last_balances:
                old = self._last_balances[xtat]
                new = card.balance
                if new != old:
                    self._last_balances[xtat] = new
                    await self._fire_balance(card, old, new)
            elif card.balance is not None:
                self._last_balances[xtat] = card.balance

            # New trips
            seen_trips = self._seen_trip_ids.setdefault(xtat, set())
            trips = await self._client.get_trips(xtat)
            for item in trips:
                if item.trip.id not in seen_trips:
                    seen_trips.add(item.trip.id)
                    await self._fire_trip(item)

            # New payments
            seen_payments = self._seen_payment_ids.setdefault(xtat, set())
            payments = await self._client.get_payments(xtat)
            for payment in payments:
                if payment.id not in seen_payments:
                    seen_payments.add(payment.id)
                    await self._fire_payment(payment)

    async def _fire_trip(self, item: TripItem) -> None:
        for cb in self._trip_cbs:
            try:
                await cb(item)
            except Exception:
                log.exception("Exception in on_new_trip callback %s", cb)

    async def _fire_payment(self, payment: Payment) -> None:
        for cb in self._payment_cbs:
            try:
                await cb(payment)
            except Exception:
                log.exception("Exception in on_new_payment callback %s", cb)

    async def _fire_balance(self, card: TransitAccount, old: int, new: int) -> None:
        for cb in self._balance_cbs:
            try:
                await cb(card, old, new)
            except Exception:
                log.exception("Exception in on_balance_changed callback %s", cb)

    def _register_event(
        self, event: str, cb: _TripCB | _PaymentCB | _BalanceCB
    ) -> None:
        if event == "new_trip":
            self._trip_cbs.append(cb)  # type: ignore
            log.info("Registered on_new_trip callback: %s", cb)
        elif event == "new_payment":
            self._payment_cbs.append(cb)  # type: ignore
            log.info("Registered on_new_payment callback: %s", cb)
        elif event == "balance_changed":
            self._balance_cbs.append(cb)  # type: ignore
            log.info("Registered on_balance_changed callback: %s", cb)
        else:
            raise ValueError(f"Unknown event: {event}")
