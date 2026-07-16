from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import OVPayClient
    from ..internals._types import (
        FaqArticleData,
        FaqArticlesPageData,
        FaqTopicData,
    )
    from ..internals.pagination import Paginator

__all__ = (
    "FaqArticle",
    "FaqArticlesPage",
    "FaqTopic",
)


@dataclass
class FaqTopic:
    """Represents a FAQ topic.

    Attributes
    ----------
    id: :class:`str`
        The unique identifier for this topic.
    name: :class:`str`
        The display name of the topic.
    """

    _client: OVPayClient
    id: str
    name: str

    @classmethod
    def from_dict(cls, client: OVPayClient, d: FaqTopicData) -> FaqTopic:
        return cls(_client=client, id=d["id"], name=d["name"])

    def get_articles(self, *, limit: int | None = None) -> Paginator[FaqArticle]:
        """Returns a paginator over every FAQ article for this topic.

        Handles pagination automatically, so you can collect all articles into a list,
        or iterate with ``async for`` to stream them one by one::

            articles = await client.get_faq_articles(topic_id)
            async for article in client.get_faq_articles(topic_id):
                ...

        Parameters
        ----------
        limit : int | None
            Maximum number of articles to return. If None, returns all articles.

        Returns
        -------
        Paginator[:class:`FaqArticle`]
        """
        return self._client.get_faq_articles(self.id, limit=limit)


@dataclass
class FaqArticle:
    """Represents a FAQ article.

    Attributes
    ----------
    id: :class:`str`
        The unique identifier for this article.
    title: :class:`str`
        The title of the article.
    topic_id: :class:`str` | :data:`None`
        The id of the topic this article belongs to, or ``None`` if unknown.
    content: :class:`str` | :data:`None`
        The full HTML/text content of the article. ``None`` when the article was
        returned as part of a listing — call :meth:`get_details` to populate it.
    """

    _client: OVPayClient
    id: str
    title: str
    topic_id: str | None
    content: str | None

    @classmethod
    def from_dict(cls, client: OVPayClient, d: FaqArticleData) -> FaqArticle:
        return cls(
            _client=client,
            id=d["id"],
            title=d["title"],
            topic_id=d.get("topicId"),
            content=d.get("content"),
        )

    async def get_details(self) -> FaqArticle:
        """Fetch the complete article, including its content."""
        return await self._client.get_faq_article(self.id)

    async def get_topic(self) -> FaqTopic | None:
        """Fetch the topic that contains this article, when known."""
        if not self.topic_id:
            return None
        topics = await self._client.get_faq_topics()
        return next((topic for topic in topics if topic.id == self.topic_id), None)


@dataclass
class FaqArticlesPage:
    """Represents a paginated list of FAQ articles.

    Attributes
    ----------
    offset: :class:`int`
        The index of the first item in this page.
    batch_size: :class:`int`
        How many items were requested per page.
    end_of_list_reached: :class:`bool`
        ``True`` when there are no more pages after this one.
    items: :class:`list`[:class:`FaqArticle`]
        The articles in this page.
    """

    _client: OVPayClient
    offset: int
    batch_size: int
    end_of_list_reached: bool
    items: list[FaqArticle] = field(default_factory=list[FaqArticle])

    @classmethod
    def from_dict(
        cls, client: OVPayClient, d: FaqArticlesPageData
    ) -> FaqArticlesPage:
        return cls(
            _client=client,
            offset=d.get("offset", 0),
            batch_size=d.get("batchSize", 0),
            end_of_list_reached=d.get("endOfListReached", False),
            items=[FaqArticle.from_dict(client, a) for a in d.get("items", [])],
        )
