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
    title: str | None
    url: str | None
    description: str | None

    @classmethod
    def from_dict(cls, d: SearchResultData) -> SearchResult:
        return cls(title=d.get("title"), url=d.get("url"), description=d.get("description"))


@dataclass
class SearchResponse:
    """Search results from GET /api/anonymous/v1/Search."""

    results: list[SearchResult]

    @classmethod
    def from_dict(cls, d: SearchResponseData) -> SearchResponse:
        return cls(results=[SearchResult.from_dict(r) for r in d.get("searchResults", [])])


@dataclass
class SearchSuggestions:
    """Search suggestions from GET /api/anonymous/v1/Search/suggestions.

    Contains both ranked search result suggestions and matching FAQ article stubs.
    """

    results: list[SearchResult]
    articles: list[dict[str, object]]

    @classmethod
    def from_dict(cls, d: SearchSuggestionsData) -> SearchSuggestions:
        return cls(
            results=[SearchResult.from_dict(r) for r in d.get("searchResults", [])],
            articles=list(d.get("articles", [])),
        )
