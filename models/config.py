from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..internals._dictable import Dictable

if TYPE_CHECKING:
    from ..internals._types import (
        AnonymousConfigData,
        WebConfigData,
    )

__all__ = (
    "AnonymousConfig",
    "WebConfig",
)


@dataclass
class AnonymousConfig(Dictable):
    """Represents the public (unauthenticated) feature configuration.

    Attributes
    ----------
    features: :class:`dict`[:class:`str`, :class:`bool`]
        Feature flags keyed by name. Use :meth:`is_enabled` to check a flag
        rather than accessing this dict directly.
    document_update_keys: :class:`dict`[:class:`str`, :class:`str`]
        Maps document names to their last-updated date strings.
    """

    features: dict[str, bool]
    document_update_keys: dict[str, str]

    def is_enabled(self, key: str) -> bool:
        return self.features.get(key, False)

    @classmethod
    def from_dict(cls, d: AnonymousConfigData) -> AnonymousConfig:
        return cls(
            features={f["key"]: f["enabled"] for f in d.get("features", [])},
            document_update_keys=dict(d.get("documentUpdateKeys", {})),
        )


@dataclass
class WebConfig(Dictable):
    """Represents the authenticated feature configuration.

    Attributes
    ----------
    features: :class:`dict`[:class:`str`, :class:`bool`]
        Feature flags keyed by name. Use :meth:`is_enabled` to check a flag
        rather than accessing this dict directly.
    """

    features: dict[str, bool]

    def is_enabled(self, key: str) -> bool:
        return self.features.get(key, False)

    @classmethod
    def from_dict(cls, d: WebConfigData) -> WebConfig:
        return cls(features={f["key"]: f["enabled"] for f in d.get("features", [])})
