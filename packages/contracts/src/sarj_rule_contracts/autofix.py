from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True, slots=True, order=True)
class TextEdit:
    """Replace a half-open range of Unicode code points in the original source."""

    start: int
    end: int
    replacement: str

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            msg = "text edit requires a nonnegative, ordered range"
            raise ValueError(msg)


def apply_edits(source: str, edits: Iterable[TextEdit]) -> str:
    ordered = sorted(set(edits))
    previous: TextEdit | None = None
    parts: list[str] = []
    cursor = 0
    for edit in ordered:
        if edit.end > len(source):
            msg = "text edit range exceeds the source"
            raise ValueError(msg)
        if previous is not None and (edit.start < previous.end or edit.start == previous.start):
            msg = "text edits overlap or have an ambiguous insertion order"
            raise ValueError(msg)
        parts.extend((source[cursor : edit.start], edit.replacement))
        cursor = edit.end
        previous = edit
    parts.append(source[cursor:])
    return "".join(parts)
