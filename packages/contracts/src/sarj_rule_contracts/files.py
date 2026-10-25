from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tempfile
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class _Snapshot:
    data: bytes
    identity: tuple[int, ...]
    mode: int
    group: int


def fix_file(
    path: Path,
    transform: Callable[[str], str],
    *,
    source_encoding: Callable[[bytes], str] | None = None,
) -> bool:
    target = path.absolute()
    original = _snapshot(target)
    encoding = (
        source_encoding(original.data)
        if source_encoding is not None
        else ("utf-8-sig" if original.data.startswith(b"\xef\xbb\xbf") else "utf-8")
    )
    source = original.data.decode(encoding)
    fixed = transform(source)
    if fixed == source:
        return False
    replacement = fixed.encode(encoding)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".sarj-fix-", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            _refuse_extended_attributes(stream.fileno())
            stream.write(replacement)
            stream.flush()
            _preserve_group(stream.fileno(), original.group)
            _preserve_mode(stream.fileno(), original.mode)
            os.fsync(stream.fileno())
            _refuse_extended_attributes(stream.fileno())
        if _snapshot(target) != original:
            message = f"source changed while fixes were prepared: {path}"
            raise ValueError(message)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _snapshot(path: Path) -> _Snapshot:
    for candidate in (path, *path.parents):
        if stat.S_ISLNK(candidate.lstat().st_mode):
            message = f"refusing to fix a symlink path: {path}"
            raise ValueError(message)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        message = f"safe fixes require a regular file with one link: {path}"
        raise ValueError(message)
    if before.st_mode & (stat.S_ISUID | stat.S_ISGID):
        message = f"safe fixes require a source without privileged permission bits: {path}"
        raise ValueError(message)
    if hasattr(os, "geteuid") and before.st_uid != os.geteuid():
        message = f"safe fixes require a source owned by the current user: {path}"
        raise ValueError(message)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _refuse_extended_attributes(stream.fileno())
        data = stream.read()
        after = os.fstat(stream.fileno())
    if _identity(before) != _identity(opened) or _identity(opened) != _identity(after):
        message = f"source changed while it was read: {path}"
        raise ValueError(message)
    return _Snapshot(data, _identity(after), stat.S_IMODE(after.st_mode), after.st_gid)


def _refuse_extended_attributes(descriptor: int) -> None:
    if not hasattr(os, "listxattr"):
        return
    try:
        attributes = os.listxattr(descriptor)
    except OSError as exc:
        message = "cannot inspect source or temporary-file extended attribute metadata"
        raise ValueError(message) from exc
    if attributes:
        message = "safe fixes require files without extended attribute metadata"
        raise ValueError(message)


def _preserve_group(descriptor: int, group: int) -> None:
    if os.fstat(descriptor).st_gid == group:
        return
    if not hasattr(os, "fchown"):
        message = "safe fixes cannot preserve source group ownership on this platform"
        raise ValueError(message)
    os.fchown(descriptor, -1, group)
    if os.fstat(descriptor).st_gid != group:
        message = "safe fixes could not preserve source group ownership"
        raise ValueError(message)


def _preserve_mode(descriptor: int, mode: int) -> None:
    if not hasattr(os, "fchmod"):
        message = "safe fixes require descriptor-based permission preservation"
        raise ValueError(message)
    os.fchmod(descriptor, mode)
    if stat.S_IMODE(os.fstat(descriptor).st_mode) != mode:
        message = "safe fixes could not preserve source permissions"
        raise ValueError(message)


def _identity(status: os.stat_result) -> tuple[int, ...]:
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
        status.st_mode,
        status.st_nlink,
        status.st_uid,
        status.st_gid,
    )
