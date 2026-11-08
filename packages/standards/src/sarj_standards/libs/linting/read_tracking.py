from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


# A rule that reads a file other than the one it checks records that path here
# before touching the filesystem, so a per-file result cache can key on it.
_READS: ContextVar[list[Path] | None] = ContextVar("sarj_standards_tracked_reads", default=None)


def record_read(path: Path) -> None:
    reads = _READS.get()
    if reads is not None:
        reads.append(path)


@contextmanager
def tracked_reads() -> Generator[list[Path]]:
    reads: list[Path] = []
    token = _READS.set(reads)
    try:
        yield reads
    finally:
        _READS.reset(token)
