"""Cross-platform filesystem predicates shared by trust boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


def is_link_like(path: Path) -> bool:
    """Treat POSIX symlinks and Windows junctions as filesystem aliases."""
    return path.is_symlink() or path.is_junction()
