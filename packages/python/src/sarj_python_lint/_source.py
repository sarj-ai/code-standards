from __future__ import annotations

from typing import TYPE_CHECKING, Final


if TYPE_CHECKING:
    from pathlib import Path


PYTHON_SOURCE_ENCODING: Final = "utf-8-sig"


def read_python_source(path: Path) -> str:
    return path.read_text(encoding=PYTHON_SOURCE_ENCODING, errors="replace")
