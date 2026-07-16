from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..internals._dictable import Dictable

if TYPE_CHECKING:
    from ..internals._types import ApiVersionData

__all__ = ("ApiVersion",)


@dataclass
class ApiVersion(Dictable):
    """Represents the API version.

    Attributes
    ----------
    major: :class:`int`
        The major version number.
    minor: :class:`int`
        The minor version number.
    patch: :class:`int`
        The patch version number.
    pre_release_tag: :class:`str`
        The pre-release tag, e.g. ``"alpha"`` or ``"rc.1"``. Empty string when absent.
    """

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
