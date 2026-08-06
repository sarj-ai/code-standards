"""Source-coordinate conversion at the boundary between analyzers and editors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .models import Position, Region


if TYPE_CHECKING:
    from typing import Self


@dataclass(slots=True)
class SourceDocument:
    """UTF-8 source with exact byte offsets and LSP-compatible UTF-16 positions."""

    path: Path
    text: str
    _lines: tuple[str, ...] = field(init=False, repr=False)
    _line_byte_offsets: tuple[int, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lines = tuple(self.text.splitlines(keepends=True)) or ("",)
        offsets: list[int] = []
        offset = 0
        for line in self._lines:
            offsets.append(offset)
            offset += len(line.encode("utf-8"))
        self._line_byte_offsets = tuple(offsets)

    @classmethod
    def read(cls, path: Path) -> Self:
        return cls(path, path.read_text(encoding="utf-8", errors="replace"))

    def point(self, *, line: int, column: int) -> Position | None:
        """Convert a one-based code-point line/column without inventing coordinates."""
        if line < 1 or column < 1 or line > len(self._lines):
            return None
        content = self._lines[line - 1].rstrip("\r\n")
        codepoint_index = column - 1
        if codepoint_index > len(content):
            return None
        prefix = content[:codepoint_index]
        return Position(
            line=line - 1,
            character=len(prefix.encode("utf-16-le")) // 2,
            byte_offset=self._line_byte_offsets[line - 1] + len(prefix.encode("utf-8")),
        )

    def region(self, *, start_byte: int, end_byte: int) -> Region:
        """Convert an exact half-open UTF-8 byte span into a UTF-16 range."""
        if start_byte < 0 or end_byte < start_byte or end_byte > len(self.text.encode("utf-8")):
            msg = "source byte range is outside the document"
            raise ValueError(msg)
        return Region(self._position_at_byte(start_byte), self._position_at_byte(end_byte))

    def _position_at_byte(self, offset: int) -> Position:
        encoded = self.text.encode("utf-8")
        prefix = encoded[:offset]
        try:
            decoded = prefix.decode("utf-8")
        except UnicodeDecodeError as exc:
            msg = "source byte offset splits a UTF-8 code point"
            raise ValueError(msg) from exc
        line = decoded.count("\n")
        current = decoded.rpartition("\n")[2]
        return Position(line=line, character=len(current.encode("utf-16-le")) // 2, byte_offset=offset)
