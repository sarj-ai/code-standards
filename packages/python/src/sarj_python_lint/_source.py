from __future__ import annotations

from io import BytesIO
import re
import tokenize
from typing import TYPE_CHECKING
import unicodedata


if TYPE_CHECKING:
    from pathlib import Path


def python_source_encoding(data: bytes) -> str:
    return tokenize.detect_encoding(BytesIO(data).readline)[0]


def read_python_source(path: Path) -> str:
    with tokenize.open(path) as stream:
        return stream.read()


def python_source_lines(source: str) -> list[str]:
    lines = re.split(r"\r\n?|\n", source)
    return lines[:-1] if not lines[-1] else lines


def symbol_prefilter_source(source: str) -> str:
    # Only necessary symbol gates may use this view; parse and locate original source.
    return source if source.isascii() else unicodedata.normalize("NFKC", source)
