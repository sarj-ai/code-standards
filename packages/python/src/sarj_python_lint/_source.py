from __future__ import annotations

from io import BytesIO
import tokenize
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


def python_source_encoding(data: bytes) -> str:
    return tokenize.detect_encoding(BytesIO(data).readline)[0]


def read_python_source(path: Path) -> str:
    with tokenize.open(path) as stream:
        return stream.read()
