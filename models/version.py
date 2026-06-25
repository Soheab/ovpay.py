from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from internals._types import ApiVersionData

__all__ = ("ApiVersion",)


@dataclass
class ApiVersion:
    """API build version from GET /api/Version."""

    major: int
    minor: int
    patch: int
    pre_release_tag: str

    @classmethod
    def from_dict(cls, d: ApiVersionData) -> ApiVersion:
        return cls(
            major=d["major"],
            minor=d["minor"],
            patch=d["patch"],
            pre_release_tag=d.get("preReleaseTag", ""),
        )
