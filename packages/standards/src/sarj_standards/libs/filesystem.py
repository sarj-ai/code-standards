from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


_READ_CHUNK_BYTES = 64 * 1024


def is_link_like(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def read_prefix(path: Path, limit: int) -> bytes:
    content = bytearray()
    with path.open("rb") as stream:
        while len(content) < limit:
            chunk = stream.read(min(_READ_CHUNK_BYTES, limit - len(content)))
            if not chunk:
                break
            content.extend(chunk)
    return bytes(content)
