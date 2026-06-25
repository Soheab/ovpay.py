from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from internals._types import (
        SearchResponseData,
        SearchResultData,
        SearchSuggestionsData,
    )

__all__ = (
    "SearchResponse",
    "SearchResult",
    "SearchSuggestions",
)


@dataclass
class SearchResult:
    """Represents a single search result.

    Attributes
    ----------
    title: :class:`str` | :data:`None`
        The page or article title.
    url: :class:`str` | :data:`None`
        The URL of the result.
    description: :class:`str` | :data:`None`
        A short description or snippet.
    """

    title: str | None
    url: str | None
    description: str | None

    @classmethod
    def from_dict(cls, d: SearchResultData) -> SearchResult:
        return cls(title=d.get("title"), url=d.get("url"), description=d.get("description"))


@dataclass
class SearchResponse:
    """Represents a search response.

    Attributes
    ----------
    results: :class:`list`[:class:`SearchResult`]
        The search results.
    """

    results: list[SearchResult]

    @classmethod
    def from_dict(cls, d: SearchResponseData) -> SearchResponse:
        return cls(results=[SearchResult.from_dict(r) for r in d.get("searchResults", [])])


@dataclass
class SearchSuggestions:
    """Represents search suggestions.

    Attributes
    ----------
    results: :class:`list`[:class:`SearchResult`]
        Ranked search result suggestions.
    articles: :class:`list`[:class:`dict`]
        Matching FAQ article stubs. The structure of each entry is not fully documented.
    """

    results: list[SearchResult]
    articles: list[dict[str, object]]

    @classmethod
    def from_dict(cls, d: SearchSuggestionsData) -> SearchSuggestions:
        return cls(
            results=[SearchResult.from_dict(r) for r in d.get("searchResults", [])],
            articles=list(d.get("articles", [])),
        )
