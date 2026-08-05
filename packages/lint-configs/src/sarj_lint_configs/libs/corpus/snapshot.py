"""Create and verify deterministic snapshots from already-local corpora."""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
import hashlib
from pathlib import Path
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- local, fixed-argument Git verification only.

from .manifest import CorpusKind, CorpusSource


_GIT_REVISION_OUTPUT_LINES = 2


@dataclass(frozen=True, slots=True, repr=False)
class CorpusSnapshot:
    """Content identity without source text or private absolute paths."""

    name: str
    digest: str
    files: int
    bytes: int
    revision: str | None = None
    private: bool = field(default=False, repr=False, compare=False)

    def __repr__(self) -> str:
        if self.private:
            return f"CorpusSnapshot(name={self.name!r}, files={self.files!r}, bytes={self.bytes!r})"
        return (
            f"CorpusSnapshot(name={self.name!r}, digest={self.digest!r}, files={self.files!r}, "
            f"bytes={self.bytes!r}, revision={self.revision!r})"
        )


def snapshot(source: CorpusSource) -> CorpusSnapshot:
    """Hash selected local bytes in stable path order without network access."""
    digest = hashlib.sha256()
    total = 0
    files = _files(source)
    if not files:
        msg = f"corpus {source.report_name} selected no files"
        raise ValueError(msg)
    for path in files:
        relative = path.relative_to(source.root).as_posix().encode()
        size = path.stat().st_size
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(size.to_bytes(8, "big"))
        read = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                read += len(chunk)
        if read != size:
            relative_name = "<private-file>" if source.visibility.value == "private" else path.relative_to(source.root)
            msg = f"corpus file changed while hashing: {relative_name}"
            raise ValueError(msg)
        total += read
    revision = _git_revision(source) if source.kind is CorpusKind.GIT else None
    return CorpusSnapshot(
        source.report_name,
        f"sha256:{digest.hexdigest()}",
        len(files),
        total,
        revision,
        private=source.visibility.value == "private",
    )


def _files(source: CorpusSource) -> tuple[Path, ...]:
    if not source.root.is_dir():
        root = "<private-corpus-root>" if source.visibility.value == "private" else source.root
        msg = f"corpus root is not a directory: {root}"
        raise ValueError(msg)
    files: list[Path] = []
    for path in source.root.rglob("*"):
        if path.is_symlink() or not path.is_file():
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
    """Require local content and Git revision to match every declared pin."""
    actual = snapshot(source)
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
    return actual


def _git_revision(source: CorpusSource) -> str:
    executable = shutil.which("git")
    if executable is None:
        msg = "git is required to verify a pinned corpus"
        raise OSError(msg)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed local Git query.
        (executable, "rev-parse", "--show-toplevel", "HEAD"),
        cwd=source.root,
        check=False,
        capture_output=True,
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
