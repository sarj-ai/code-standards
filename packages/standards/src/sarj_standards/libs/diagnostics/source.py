from __future__ import annotations

from array import array
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import TYPE_CHECKING, NamedTuple

from sarj_rule_contracts import SourceSnapshot

from .models import Position, Region


if TYPE_CHECKING:
    from typing import Self


class _Utf16Index(NamedTuple):
    starts: array[int]
    ends: array[int]
    unit_extras: array[int]
    byte_extras: array[int]


@dataclass(frozen=True, slots=True)
class _CoordinateIndex:
    text: str
    lines: tuple[str, ...]
    line_byte_offsets: tuple[int, ...]
    byte_length: int
    utf16_indexes: dict[int, _Utf16Index] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def build(cls, text: str) -> Self:
        lines = tuple(re.findall(r".*?(?:\r\n|\r|\n)|.+\Z", text, flags=re.DOTALL)) or ("",)
        if text.endswith(("\n", "\r")):
            lines = (*lines, "")
        offsets: list[int] = []
        offset = 0
        for line in lines:
            offsets.append(offset)
            offset += len(line.encode("utf-8", errors="surrogateescape"))
        return cls(text, lines, tuple(offsets), offset)


@dataclass(slots=True)
class SourceDocument:
    path: Path
    text: str
    _index: _CoordinateIndex = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._index = _CoordinateIndex.build(self.text)

    def _coordinate_index(self) -> _CoordinateIndex:
        text = self.text
        index = self._index
        if index.text is not text:
            index = _CoordinateIndex.build(text)
            self._index = index
        return index

    @classmethod
    def read(cls, path: Path) -> Self:
        return cls.from_snapshot(SourceSnapshot.read(path))

    @classmethod
    def from_snapshot(cls, snapshot: SourceSnapshot) -> Self:
        return cls(snapshot.path, snapshot.decode("utf-8", errors="surrogateescape").text)

    def point(self, *, line: int, column: int) -> Position | None:
        index = self._coordinate_index()
        if line < 1 or column < 1 or line > len(index.lines):
            return None
        source_line = index.lines[line - 1]
        codepoint_index = column - 1
        if source_line.isascii():
            if codepoint_index > _content_length(source_line):
                return None
            return Position(line - 1, codepoint_index, index.line_byte_offsets[line - 1] + codepoint_index)
        content = source_line.rstrip("\r\n")
        if codepoint_index > len(content):
            return None
        prefix = content[:codepoint_index]
        return Position(
            line=line - 1,
            character=len(prefix.encode("utf-16-le", errors="surrogatepass")) // 2,
            byte_offset=(index.line_byte_offsets[line - 1] + len(prefix.encode("utf-8", errors="surrogateescape"))),
        )

    def utf16_point(self, *, line: int, character: int) -> Position | None:
        document = self._coordinate_index()
        if line < 0 or character < 0 or line >= len(document.lines):
            return None
        source_line = document.lines[line]
        if character == 0:
            return Position(line=line, character=0, byte_offset=document.line_byte_offsets[line])
        if source_line.isascii():
            if character > _content_length(source_line):
                return None
            return Position(
                line=line,
                character=character,
                byte_offset=document.line_byte_offsets[line] + character,
            )
        content = source_line.rstrip("\r\n")
        index = document.utf16_indexes.get(line)
        if index is None:
            index = self._build_utf16_index(content)
            document.utf16_indexes[line] = index
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
            byte_offset=document.line_byte_offsets[line] + codepoint_index + byte_extra,
        )

    @staticmethod
    def _build_utf16_index(content: str) -> _Utf16Index:
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
        return _Utf16Index(starts, ends, unit_extras, byte_extras)

    def byte_point(self, *, line: int, column: int) -> Position | None:
        index = self._coordinate_index()
        if line < 1 or column < 1 or line > len(index.lines):
            return None
        source_line = index.lines[line - 1]
        byte_column = column - 1
        if source_line.isascii():
            if byte_column > _content_length(source_line):
                return None
            return Position(line - 1, byte_column, index.line_byte_offsets[line - 1] + byte_column)
        content = source_line.rstrip("\r\n")
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
            byte_offset=index.line_byte_offsets[line - 1] + byte_column,
        )

    def region(self, *, start_byte: int, end_byte: int) -> Region:
        index = self._coordinate_index()
        if start_byte < 0 or end_byte < start_byte or end_byte > index.byte_length:
            msg = "source byte range is outside the document"
            raise ValueError(msg)
        return Region(self._position_at_byte(start_byte, index), self._position_at_byte(end_byte, index))

    @staticmethod
    def _position_at_byte(offset: int, index: _CoordinateIndex) -> Position:
        if offset < 0 or offset > index.byte_length:
            msg = "source byte offset is outside the document"
            raise ValueError(msg)
        line = bisect_right(index.line_byte_offsets, offset) - 1
        line_start = index.line_byte_offsets[line]
        relative = offset - line_start
        source_line = index.lines[line]
        if source_line.isascii():
            if 0 < relative < len(source_line) and source_line[relative - 1] == "\r" and source_line[relative] == "\n":
                msg = "source byte offset splits a CRLF line terminator"
                raise ValueError(msg)
            return Position(line, relative, offset)
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


def _content_length(line: str) -> int:
    # Indexed lines have at most one protocol terminator; avoid copying long lines.
    if line.endswith("\r\n"):
        return len(line) - 2
    return len(line) - int(line.endswith(("\r", "\n")))
