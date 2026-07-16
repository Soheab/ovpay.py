from __future__ import annotations

import dataclasses
import datetime
from typing import Any

__all__ = ("Dictable",)

type ToDictV = (
    Dictable
    | datetime.datetime
    | datetime.date
    | list[Any]
    | dict[str, Any]
    | str
    | int
    | float
    | bool
    | None
)


def _convert(value: ToDictV) -> ToDictV:
    if isinstance(value, Dictable):
        return value.to_dict()
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_convert(v) for v in value]
    if isinstance(value, dict):
        return {k: _convert(v) for k, v in value.items()}
    return value


class Dictable:
    """Mixin providing :meth:`to_dict` for dataclasses.

    Fields whose name starts with an underscore (e.g. internal client
    references) are omitted from the result.
    """

    def to_dict(self) -> dict[str, ToDictV]:
        if not dataclasses.is_dataclass(self):
            raise TypeError(f"{self.__class__.__name__} is not a dataclass")

        return {
            f.name: _convert(getattr(self, f.name))
            for f in dataclasses.fields(self)
            if not f.name.startswith("_")
        }
