from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from internals._types import (
        AnonymousConfigData,
        WebConfigData,
    )

__all__ = (
    "AnonymousConfig",
    "WebConfig",
)


@dataclass
class AnonymousConfig:
    """Public (unauthenticated) feature flags from GET /api/anonymous/V2/Config.

    Different from the authenticated WebConfig — these flags cover public-facing
    features like anonymous OV-card ordering, top-up, chatbot, etc.
    Use is_enabled(key) to check a flag, e.g. is_enabled("WebLoginEnabled").
    document_update_keys maps document names to their last-updated date strings.
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
class WebConfig:
    """Feature flags from GET /api/v1/WebConfig.

    Use is_enabled(key) to check a feature flag by its string key, e.g.:
        config.is_enabled("TopUpBalanceEnabled")
    """

    features: dict[str, bool]

    def is_enabled(self, key: str) -> bool:
        return self.features.get(key, False)

    @classmethod
    def from_dict(cls, d: WebConfigData) -> WebConfig:
        return cls(features={f["key"]: f["enabled"] for f in d.get("features", [])})
