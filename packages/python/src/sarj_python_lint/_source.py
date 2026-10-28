from __future__ import annotations

from io import BytesIO
import re
import tokenize
from typing import TYPE_CHECKING
import unicodedata

from sarj_rule_contracts import NewlinePolicy, SourceSnapshot


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_rule_contracts import SourceCatalog


def python_source_encoding(data: bytes) -> str:
    return tokenize.detect_encoding(BytesIO(data).readline)[0]


def read_python_source(path: Path, *, sources: SourceCatalog | None = None) -> str:
    snapshot = SourceSnapshot.read(path) if sources is None else sources.capture(path)
    return decode_python_source(snapshot)


def decode_python_source(snapshot: SourceSnapshot) -> str:
    return snapshot.decode(python_source_encoding(snapshot.raw), newlines=NewlinePolicy.UNIVERSAL).text


def python_source_lines(source: str) -> list[str]:
    lines = re.split(r"\r\n?|\n", source)
    return lines[:-1] if not lines[-1] else lines


def symbol_prefilter_source(source: str) -> str:
    # Only necessary symbol gates may use this view; parse and locate original source.
    return source if source.isascii() else unicodedata.normalize("NFKC", source)
