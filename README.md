# ovpay.py

An unofficial asynchronous Python client for the OVpay API.

Provides typed Python models for transit accounts (what OVpay calls a card or
*pas* in the UI), trips, payments, receipts, customer details, OVpay
configuration, FAQ articles, search results, and address lookups.

> [!WARNING]
> This project is not affiliated with or endorsed by OVpay or Translink. It uses
> undocumented APIs, so endpoints and response formats may change without notice.

## Requirements

- Python 3.12 or newer
- An OVpay account
- A browser session logged in at [ovpay.nl](https://www.ovpay.nl/)

## Installation

This project is not published on PyPI. Install it directly from GitHub:

```bash
pip install "git+https://github.com/soheab/ovpay.py.git"
```

Or clone and install locally:

```bash
git clone https://github.com/soheab/ovpay.py.git
cd ovpay.py
pip install .
```

For development with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/soheab/ovpay.py.git
cd ovpay.py
uv sync
```

## Authentication

OVpay does not provide a public API key flow. The client supports two methods:

- **Session cookie** — allows automatic token refresh, lasts weeks. Recommended.
- **Access token** — copied from an active browser session, expires in ~1 hour.

### Getting the session cookie

1. Sign in at [ovpay.nl](https://www.ovpay.nl/).
2. Open browser developer tools and go to the **Network** tab.
3. Reload the page and click any request to `www.ovpay.nl`.
4. In the **Headers** tab, find the `cookie:` request header and copy its entire value.

The client automatically extracts the `__Secure-next-auth.session-token` cookie
(including its `.0`/`.1` chunks if NextAuth split it) and ignores the rest.
You can paste the entire browser cookie header — no need to strip it manually.

Save it to a file (recommended):

```
__Secure-next-auth.session-token.0=eyJ...; __Secure-next-auth.session-token.1=eyJ...
```

Then pass the file path:

```python
import asyncio
from pathlib import Path

from ovpay import OVPayClient


async def main() -> None:
    async with OVPayClient(cookie=Path("cookies.txt")) as client:
        cards = await client.get_transit_accounts()
        for card in cards:
            print(card.name, card.balance_euros)


asyncio.run(main())
```

Or pass the cookie string directly:

```python
async with OVPayClient(cookie="__Secure-next-auth.session-token.0=eyJ...") as client:
    ...
```

### Getting an access token

1. Sign in at [ovpay.nl](https://www.ovpay.nl/).
2. Navigate to [https://www.ovpay.nl/api/auth/session](https://www.ovpay.nl/api/auth/session).
3. Copy the value of the `token` field (without quotes).

```python
import asyncio

from ovpay import OVPayClient


async def main() -> None:
    async with OVPayClient(token="eyJ...") as client:
        cards = await client.get_transit_accounts()
        print(cards)


asyncio.run(main())
```

> [!CAUTION]
> Never commit tokens or cookies to Git. Store them in an ignored file,
> environment variable, or secret manager.

## Examples

### Fetch trips

```python
import asyncio
from pathlib import Path

from ovpay import OVPayClient


async def main() -> None:
    async with OVPayClient(cookie=Path("cookies.txt")) as client:
        cards = await client.get_transit_accounts()
        for card in cards:
            async for trip in card.get_trips():
                print(
                    trip.trip.check_in_timestamp,
                    trip.trip.check_in_location,
                    trip.trip.check_out_location,
                    trip.trip.fare_euros,
                )


asyncio.run(main())
```

### Fetch payments

```python
import asyncio
from pathlib import Path

from ovpay import OVPayClient


async def main() -> None:
    async with OVPayClient(cookie=Path("cookies.txt")) as client:
        cards = await client.get_transit_accounts()
        for card in cards:
            payments = await card.get_payments()
            for payment in payments:
                print(card.name, payment.transaction_timestamp, payment.amount_euros)


asyncio.run(main())
```

### Export trips as PDF or CSV

```python
import asyncio
from datetime import date
from pathlib import Path

from ovpay import OVPayClient


async def main() -> None:
    async with OVPayClient(cookie=Path("cookies.txt")) as client:
        pdf = await client.export_trips_pdf(date(2026, 1, 1), date(2026, 1, 31))
        Path("trips.pdf").write_bytes(pdf)

        csv = await client.export_trips_csv(date(2026, 1, 1), date(2026, 1, 31))
        Path("trips.csv").write_bytes(csv)


asyncio.run(main())
```

### Look up a transit account by card number

Useful when you have the 16-digit number from the physical card or the
OV-chipkaart and need the OVpay XTAT/XBOT tokens:

```python
async with OVPayClient(cookie=Path("cookies.txt")) as client:
    results = await client.find_transit_account(card_number="3528070062952239")
    print(results[0].xtat)
```

## Poller / Events

The client has a built-in background poller that watches your cards for changes
and fires async callbacks when they occur. Enable it with `enable_poller=True`
and register handlers using the `@client.event()` decorator.

Three events are available:

| Event                  | Callback signature                                         | Fires when                                 |
| ---------------------- | ---------------------------------------------------------- | ------------------------------------------ |
| `on_new_trip`        | `async def fn(trip: TripItem)`                           | A new trip appears                         |
| `on_new_payment`     | `async def fn(payment: Payment)`                         | A new payment appears                      |
| `on_balance_changed` | `async def fn(card: TransitAccount, old: int, new: int)` | A card's balance changes (values in cents) |

```python
import asyncio
from pathlib import Path

from ovpay import OVPayClient, TripItem, Payment, TransitAccount

client = OVPayClient(cookie=Path("cookies.txt"), enable_poller=True, poller_interval=60)


@client.event()
async def on_new_trip(trip: TripItem) -> None:
    print(f"New trip: {trip.trip.check_in_location} → {trip.trip.check_out_location} (€{trip.trip.fare_euros})")


@client.event()
async def on_new_payment(payment: Payment) -> None:
    print(f"New payment: €{payment.amount_euros} at {payment.transaction_timestamp}")


@client.event()
async def on_balance_changed(card: TransitAccount, old: int, new: int) -> None:
    print(f"{card.name}: €{old / 100:.2f} → €{new / 100:.2f}")


asyncio.run(client.start())
```

The poller seeds itself on startup (no callbacks fire for existing data) and
polls every `poller_interval` seconds thereafter. Errors in a poll cycle are
logged and retried on the next interval.

## Available APIs

| Method                                        | Description                                          |
| --------------------------------------------- | ---------------------------------------------------- |
| `get_transit_accounts()`                    | All linked cards, optionally with personalization    |
| `get_transit_account(xtat)`                 | Single card by XTAT token                            |
| `find_transit_account(card_number=…)`      | Look up card by number, mediumId, or hashed mediumId |
| `get_transit_account_products(xtat)`        | Products and age-discount profile for a card         |
| `get_token_details(xbot)`                   | Card details by XBOT token                           |
| `get_trips(xtat)`                           | Paginated trip history for a card                    |
| `get_trip_details(xbot, id)`                | Full detail for a single trip                        |
| `export_trips(from, to)`                    | Paginated trip export for a date range               |
| `export_trips_query(query)`                 | Trip export with filters via`ExportQuery`          |
| `export_trips_pdf(from, to)`                | Download trip export as PDF                          |
| `export_trips_csv(from, to)`                | Download trip export as CSV                          |
| `get_payments(xtat)`                        | Paginated payment history for a card                 |
| `get_payment_receipt(xbot, id)`             | Receipt for a single payment                         |
| `get_passenger_account()`                   | Basic account info (email)                           |
| `get_customer()`                            | Full profile: name, address, phone, ARL contracts    |
| `get_web_config()`                          | Authenticated feature flags                          |
| `get_anonymous_config()`                    | Public feature flags                                 |
| `get_version()`                             | API build version                                    |
| `get_faq_topics()`                          | All FAQ topic categories                             |
| `get_faq_articles(topic_id)`                | Paginated articles in a topic                        |
| `get_faq_topic_articles(topic_id)`          | Same via topic path endpoint                         |
| `get_faq_article(article_id)`               | Single article with full content                     |
| `get_faq_topic_by_name(slug)`               | Topic by URL slug                                    |
| `search(query)`                             | Full-text search across help content                 |
| `get_search_suggestions(query)`             | Autocomplete suggestions                             |
| `get_ovpas_price(token_type)`               | Public OV-pas pricing                                |
| `lookup_address(postal_code, house_number)` | Authenticated address lookup                         |
| `lookup_address_anonymously(…)`            | Anonymous address lookup                             |

Paginated methods return a `Paginator` that can be awaited to collect all
results or iterated with `async for` to stream results page by page.

## License

[Mozilla Public License 2.0](LICENSE) — © Soheab.

You may use and modify this library, but any modifications to its files must
also be released under MPL 2.0. You may not republish it as your own.

## Notes

- Monetary values are in euro cents internally. Models expose `balance_euros`,
  `fare_euros`, and `amount_euros` convenience properties.
- Cookie-backed clients refresh their access token automatically when it expires.
- Static access tokens cannot be refreshed and expire in ~1 hour.
- Always close the client — use `async with` or call `await client.close()`.
