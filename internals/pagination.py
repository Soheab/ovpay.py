from __future__ import annotations

from collections.abc import Callable, Coroutine, Generator
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

T = TypeVar("T")


class PaginatorItem[T](Protocol):
    """Protocol for a single page of items returned by a paginated endpoint.

    A page object must expose an ``items`` attribute (a list of items) and an
    ``end_of_list_reached`` attribute (a bool).
    """

    items: list[T]
    end_of_list_reached: bool


class Paginator[T]:
    """Lazily fetches successive pages from a paginated OVpay endpoint.

    A :class:`Paginator` is both awaitable and async-iterable, so callers may
    choose how the underlying pages are consumed:

    Collect every item into a single list (fetches all pages eagerly)::

        items = await client.get_trips(xtat)

    Iterate item-by-item, fetching pages on demand::

        async for trip in client.get_trips(xtat):
            ...
    """

    def __init__(
        self,
        fetch_page: Callable[[int], Coroutine[Any, Any, PaginatorItem[T]]],
        *,
        limit: int | None = None,
    ) -> None:
        self._fetch_page: Callable[[int], Coroutine[Any, Any, PaginatorItem[T]]] = (
            fetch_page
        )
        self._limit: int | None = limit

    async def __aiter__(self) -> AsyncIterator[T]:
        offset = 0
        yielded = 0
        while True:
            if self._limit is not None and yielded >= self._limit:
                return
            page = await self._fetch_page(offset)
            items = page.items  # type: ignore[attr-defined]
            for item in items:
                yield item
                yielded += 1
                if self._limit is not None and yielded >= self._limit:
                    return

            if page.end_of_list_reached or not items:
                return
            offset += len(items)

    async def flatten(self) -> list[T]:
        """:class:`list[T]`: Fetches all pages and returns a single list of items."""
        return [item async for item in self]

    def __await__(self) -> Generator[object, None, list[T]]:
        return self.flatten().__await__()
