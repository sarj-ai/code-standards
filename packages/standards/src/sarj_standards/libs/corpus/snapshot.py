from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- local, fixed-argument Git verification only.
from typing import Final, NamedTuple

from sarj_standards.libs.filesystem import is_link_like

from .manifest import CorpusKind, CorpusSource


_GIT_REVISION_OUTPUT_LINES = 2
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_GIT_SAFE_ENV: Final = frozenset(
    {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TMPDIR", "XDG_CONFIG_HOME"}
)


@dataclass(frozen=True, slots=True, repr=False)
class CorpusSnapshot:
    name: str
    digest: str
    files: int
    bytes: int
    revision: str | None = None
    private: bool = field(default=False, repr=False, compare=False)
    verified: bool = field(default=False, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.name or not _DIGEST.fullmatch(self.digest):
            msg = "corpus snapshot requires a name and sha256 digest"
            raise ValueError(msg)
        if self.files <= 0 or self.bytes < 0:
            msg = "corpus snapshot counts must contain files and non-negative bytes"
            raise ValueError(msg)
        if self.revision is not None and not _REVISION.fullmatch(self.revision):
            msg = "corpus snapshot revision must be a full lowercase Git revision"
            raise ValueError(msg)

    def __repr__(self) -> str:
        if self.private:
            return f"CorpusSnapshot(name={self.name!r}, files={self.files!r}, bytes={self.bytes!r})"
        return (
            f"CorpusSnapshot(name={self.name!r}, digest={self.digest!r}, files={self.files!r}, "
            f"bytes={self.bytes!r}, revision={self.revision!r})"
        )


class VerifiedInventory(NamedTuple):
    snapshot: CorpusSnapshot
    files: tuple[Path, ...]


def snapshot(source: CorpusSource) -> CorpusSnapshot:
    return snapshot_inventory(source, selected_files(source))


def snapshot_inventory(source: CorpusSource, files: tuple[Path, ...]) -> CorpusSnapshot:
    initial_revision = _git_revision(source) if source.kind is CorpusKind.GIT else None
    digest = hashlib.sha256()
    total = 0
    if not files:
        msg = f"corpus {source.report_name} selected no files"
        raise ValueError(msg)
    for path in files:
        relative = path.relative_to(source.root).as_posix().encode()
        before = path.stat()
        size = before.st_size
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(size.to_bytes(8, "big"))
        read = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                read += len(chunk)
        after = path.stat()
        if read != size or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ):
            relative_name = "<private-file>" if source.visibility.value == "private" else path.relative_to(source.root)
            msg = f"corpus file changed while hashing: {relative_name}"
            raise ValueError(msg)
        total += read
    revision = _git_revision(source) if source.kind is CorpusKind.GIT else None
    if revision != initial_revision:
        msg = f"corpus {source.report_name} revision changed while hashing"
        raise ValueError(msg)
    return CorpusSnapshot(
        source.report_name,
        f"sha256:{digest.hexdigest()}",
        len(files),
        total,
        revision,
        private=source.visibility.value == "private",
    )


def selected_files(source: CorpusSource) -> tuple[Path, ...]:
    if not source.root.is_dir():
        root = "<private-corpus-root>" if source.visibility.value == "private" else source.root
        msg = f"corpus root is not a directory: {root}"
        raise ValueError(msg)
    candidates = _git_tracked_files(source) if source.kind is CorpusKind.GIT else source.root.rglob("*")
    files: list[Path] = []
    for path in candidates:
        if is_link_like(path) or not path.is_file():
            continue
        relative = path.relative_to(source.root).as_posix()
        if _matches(relative, source.include) and not _matches(relative, source.exclude):
            files.append(path)
    return tuple(sorted(files, key=lambda path: path.relative_to(source.root).as_posix()))


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(
        fnmatch(path, pattern) or (pattern.startswith("**/") and fnmatch(path, pattern[3:])) for pattern in patterns
    )


def verify(source: CorpusSource) -> CorpusSnapshot:
    verified, _files = verify_inventory(source)
    return verified


def verify_inventory(source: CorpusSource) -> VerifiedInventory:
    files = selected_files(source)
    actual = snapshot_inventory(source, files)
    if actual.digest != source.digest:
        if actual.private:
            msg = f"corpus {source.report_name} digest drifted"
        else:
            msg = f"corpus {source.report_name} digest drifted: expected {source.digest}, found {actual.digest}"
        raise ValueError(msg)
    if source.kind is CorpusKind.GIT and actual.revision != source.revision:
        if actual.private:
            msg = f"corpus {source.report_name} revision drifted"
        else:
            msg = f"corpus {source.report_name} revision drifted: expected {source.revision}, found {actual.revision}"
        raise ValueError(msg)
    verified = CorpusSnapshot(
        actual.name,
        actual.digest,
        actual.files,
        actual.bytes,
        actual.revision,
        private=actual.private,
    )
    object.__setattr__(verified, "verified", True)  # ruff: ignore[unnecessary-dunder-call] -- frozen evidence token.
    return VerifiedInventory(verified, files)


def _git_revision(source: CorpusSource) -> str:
    executable = shutil.which("git")
    if executable is None:
        msg = "git is required to verify a pinned corpus"
        raise OSError(msg)
    environment = _git_environment()
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed local Git query.
        (executable, "rev-parse", "--show-toplevel", "HEAD"),
        cwd=source.root,
        check=False,
        capture_output=True,
        env=environment,
        shell=False,
        text=True,
    )
    lines = completed.stdout.splitlines()
    if completed.returncode or len(lines) != _GIT_REVISION_OUTPUT_LINES:
        msg = f"could not read Git revision for corpus {source.report_name}"
        raise ValueError(msg)
    top_level, revision = lines
    if Path(top_level).resolve() != source.root.resolve():
        msg = f"Git repository root does not match corpus {source.report_name} root"
        raise ValueError(msg)
    return revision


def _git_tracked_files(source: CorpusSource) -> tuple[Path, ...]:
    executable = shutil.which("git")
    if executable is None:
        msg = "git is required to select tracked corpus files"
        raise OSError(msg)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed local Git query.
        (executable, "ls-files", "-z"),
        cwd=source.root,
        check=False,
        capture_output=True,
        env=_git_environment(),
        shell=False,
        text=True,
    )
    if completed.returncode:
        msg = f"could not list tracked files for corpus {source.report_name}"
        raise ValueError(msg)
    return tuple(source.root / relative for relative in completed.stdout.split("\0") if relative)


def _git_environment() -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()  # ruff: ignore[banned-api] -- discard hook-local repository routing.
        if name in _GIT_SAFE_ENV
    }
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
        }
    )
    return environment
