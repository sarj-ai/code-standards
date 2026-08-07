"""Source-coordinate conversion at the boundary between analyzers and editors."""

from __future__ import annotations

from array import array
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
import re
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
    _byte_length: int = field(init=False, repr=False)
    _utf16_indexes: dict[int, tuple[array[int], array[int], array[int], array[int]]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        lines = tuple(re.findall(r".*?(?:\r\n|\r|\n)|.+\Z", self.text, flags=re.DOTALL)) or ("",)
        if self.text.endswith(("\n", "\r")):
            lines = (*lines, "")
        self._lines = lines
        offsets: list[int] = []
        offset = 0
        for line in self._lines:
            offsets.append(offset)
            offset += len(line.encode("utf-8", errors="surrogateescape"))
        self._line_byte_offsets = tuple(offsets)
        self._byte_length = offset
        self._utf16_indexes = {}

    @classmethod
    def read(cls, path: Path) -> Self:
        return cls(path, path.read_bytes().decode("utf-8", errors="surrogateescape"))

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
            character=len(prefix.encode("utf-16-le", errors="surrogatepass")) // 2,
            byte_offset=(self._line_byte_offsets[line - 1] + len(prefix.encode("utf-8", errors="surrogateescape"))),
        )

    def utf16_point(self, *, line: int, character: int) -> Position | None:
        """Resolve an already-zero-based UTF-16 position to its byte offset."""
        if line < 0 or character < 0 or line >= len(self._lines):
            return None
        content = self._lines[line].rstrip("\r\n")
        if character == 0:
            return Position(line=line, character=0, byte_offset=self._line_byte_offsets[line])
        if content.isascii():
            if character > len(content):
                return None
            return Position(
                line=line,
                character=character,
                byte_offset=self._line_byte_offsets[line] + character,
            )
        index = self._utf16_indexes.get(line)
        if index is None:
            index = self._build_utf16_index(content)
            self._utf16_indexes[line] = index
        starts, ends, unit_extras, byte_extras = index
        event_index = bisect_right(ends, character)
        if event_index < len(starts) and starts[event_index] < character < ends[event_index]:
            return None
        unit_extra = unit_extras[event_index - 1] if event_index else 0
        byte_extra = byte_extras[event_index - 1] if event_index else 0
        codepoint_index = character - unit_extra
        if codepoint_index < 0 or codepoint_index > len(content):
            return None
        return Position(
            line=line,
            character=character,
            byte_offset=self._line_byte_offsets[line] + codepoint_index + byte_extra,
        )

    @staticmethod
    def _build_utf16_index(content: str) -> tuple[array[int], array[int], array[int], array[int]]:
        starts = array("I")
        ends = array("I")
        unit_extras = array("I")
        byte_extras = array("I")
        utf16_offset = 0
        byte_offset = 0
        for codepoint_index, value in enumerate(content):
            units = len(value.encode("utf-16-le", errors="surrogatepass")) // 2
            byte_length = len(value.encode("utf-8", errors="surrogateescape"))
            if units != 1 or byte_length != 1:
                end = utf16_offset + units
                starts.append(utf16_offset)
                ends.append(end)
                unit_extras.append(end - codepoint_index - 1)
                byte_extras.append(byte_offset + byte_length - codepoint_index - 1)
            utf16_offset += units
            byte_offset += byte_length
        return starts, ends, unit_extras, byte_extras

    def byte_point(self, *, line: int, column: int) -> Position | None:
        """Convert a one-based line and UTF-8 byte column without guessing."""
        if line < 1 or column < 1 or line > len(self._lines):
            return None
        content = self._lines[line - 1].rstrip("\r\n")
        byte_column = column - 1
        encoded = content.encode("utf-8", errors="surrogateescape")
        if byte_column > len(encoded):
            return None
        try:
            prefix = encoded[:byte_column].decode("utf-8", errors="surrogateescape")
        except ValueError:
            return None
        if not content.startswith(prefix):
            return None
        return Position(
            line=line - 1,
            character=len(prefix.encode("utf-16-le", errors="surrogatepass")) // 2,
            byte_offset=self._line_byte_offsets[line - 1] + byte_column,
        )

    def region(self, *, start_byte: int, end_byte: int) -> Region:
        """Convert an exact half-open UTF-8 byte span into a UTF-16 range."""
        if start_byte < 0 or end_byte < start_byte or end_byte > self._byte_length:
            msg = "source byte range is outside the document"
            raise ValueError(msg)
        return Region(self._position_at_byte(start_byte), self._position_at_byte(end_byte))

    def _position_at_byte(self, offset: int) -> Position:
        if offset < 0 or offset > self._byte_length:
            msg = "source byte offset is outside the document"
            raise ValueError(msg)
        line = bisect_right(self._line_byte_offsets, offset) - 1
        line_start = self._line_byte_offsets[line]
        relative = offset - line_start
        source_line = self._lines[line]
        encoded_line = source_line.encode("utf-8", errors="surrogateescape")
        if relative > 0 and relative < len(encoded_line) and encoded_line[relative - 1 : relative + 1] == b"\r\n":
            msg = "source byte offset splits a CRLF line terminator"
            raise ValueError(msg)
        prefix = encoded_line[:relative]
        try:
            decoded = prefix.decode("utf-8", errors="surrogateescape")
        except UnicodeDecodeError as exc:
            msg = "source byte offset splits a UTF-8 code point"
            raise ValueError(msg) from exc
        if not source_line.startswith(decoded):
            msg = "source byte offset splits a UTF-8 code point"
            raise ValueError(msg)
        local_newlines = decoded.count("\n")
        current = decoded.rpartition("\n")[2]
        return Position(
            line=line + local_newlines,
            character=len(current.encode("utf-16-le", errors="surrogatepass")) // 2,
            byte_offset=offset,
        )
