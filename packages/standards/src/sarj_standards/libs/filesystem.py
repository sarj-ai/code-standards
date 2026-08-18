from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


def is_link_like(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()
