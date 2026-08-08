"""Best-effort file transaction for adoption and upgrade operations."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tempfile
from typing import Final, Self

from sarj_lint_configs.libs.filesystem import is_link_like


_OWNED_NAMES: Final = frozenset(
    {
        ".pre-commit-config.yaml",
        ".pre-commit-config.yml",
        ".sarj-standards.toml",
        ".ruff-strict.toml",
        ".pyright-strict.json",
        ".markdownlint.yaml",
        ".taplo.toml",
        ".yamllint.yaml",
        "eslint.config.mjs",
        "eslint.strict.mjs",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lock",
        "bun.lockb",
        "pyproject.toml",
        "pyrightconfig.json",
        "pyrightconfig.jsonc",
        "uv.lock",
    }
)
_SKIP_DIRS: Final = frozenset({".git", ".venv", "node_modules", "dist", "build", ".next", ".cache"})
_INSTALL_MUTATION_NAMES: Final = frozenset(
    {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lock",
        "bun.lockb",
        "pyproject.toml",
        "uv.lock",
    }
)


def validate_targets(root: Path, paths: tuple[Path, ...]) -> None:
    """Reject mutation targets that escape the repo or traverse a symlink."""
    resolved_root = root.resolve()
    lexical_root = root.absolute()
    for path in paths:
        try:
            relative = path.absolute().relative_to(lexical_root)
        except ValueError as exc:
            msg = f"mutation target {path} escapes repository root {resolved_root}"
            raise OSError(msg) from exc
        current = lexical_root
        for part in relative.parts:
            current /= part
            if is_link_like(current):
                msg = f"refusing symlink mutation target {path}; link traversal at {current}"
                raise OSError(msg)
        if path.exists() and not path.is_file():
            msg = f"refusing non-file mutation target {path}"
            raise OSError(msg)
        if path.is_file() and path.stat(follow_symlinks=False).st_nlink > 1:
            msg = f"refusing hard-linked mutation target {path}"
            raise OSError(msg)
        try:
            path.resolve().relative_to(resolved_root)
        except (OSError, ValueError) as exc:
            msg = f"mutation target {path} escapes repository root {resolved_root}"
            raise OSError(msg) from exc


def atomic_write_text(root: Path, path: Path, contents: str) -> None:
    """Replace one validated file without following a swapped final symlink."""
    atomic_write_bytes(root, path, contents.encode("utf-8"))


def atomic_write_bytes(root: Path, path: Path, contents: bytes) -> None:
    """Replace one validated binary file without following a swapped final symlink."""
    validate_targets(root, (path,))
    path.parent.mkdir(parents=True, exist_ok=True)
    validate_targets(root, (path,))
    mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode) if path.is_file() else 0o644
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        _write_temporary(descriptor, contents, mode)
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def assert_expected(root: Path, path: Path, expected: bytes | None) -> None:
    """Fail immediately when a planned target changed after its plan was built."""
    validate_targets(root, (path,))
    current = path.read_bytes() if path.is_file() else None
    if current != expected:
        msg = f"planned mutation target changed concurrently: {path}; rerun the command"
        raise OSError(msg)


def _write_temporary(descriptor: int, contents: bytes, mode: int) -> None:
    with os.fdopen(descriptor, "wb") as handle:
        os.fchmod(handle.fileno(), mode)
        _ = handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())


@dataclass
class FileSnapshot:
    """Recoverable state for one file that existed before an operation."""

    contents: bytes | None
    mode: int | None


@dataclass(frozen=True, slots=True)
class RollbackIssue:
    """One path that could not be restored without risking more data loss."""

    path: Path
    detail: str


@dataclass(frozen=True, slots=True)
class RollbackReport:
    """Best-effort rollback outcome; recovery failures never raise recursively."""

    issues: tuple[RollbackIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    def render(self) -> str | None:
        if not self.issues:
            return None
        return "; ".join(f"could not restore {issue.path}: {issue.detail}" for issue in self.issues)


@dataclass
class FileTransaction:
    """Snapshot likely mutation targets and restore them after a failed operation."""

    root: Path
    before: dict[Path, FileSnapshot]
    written: dict[Path, bytes | None]
    absent_parents: set[Path]

    @classmethod
    def capture(cls, root: Path, extra: tuple[Path, ...] = ()) -> Self:
        resolved = root.resolve()
        candidates = set(extra)
        for parent, directories, names in os.walk(resolved):
            directories[:] = [name for name in directories if name not in _SKIP_DIRS]
            directory = Path(parent)
            candidates.update(directory / name for name in names if name in _OWNED_NAMES)
            if "pyproject.toml" in names:
                candidates.add(directory / "uv.lock")
            if "package.json" in names:
                candidates.update(
                    directory / name
                    for name in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb")
                )
        before: dict[Path, FileSnapshot] = {}
        absent_parents: set[Path] = set()
        for path in candidates:
            if is_link_like(path):
                if path.name in _INSTALL_MUTATION_NAMES:
                    msg = f"refusing linked dependency transaction target {path}"
                    raise OSError(msg)
                continue
            try:
                path.resolve().relative_to(resolved)
            except OSError, ValueError:
                continue
            if path.is_file() and path.stat(follow_symlinks=False).st_nlink > 1:
                msg = f"refusing hard-linked transaction target {path}"
                raise OSError(msg)
            before[path] = _snapshot(path)
            absent_parents.update(_absent_parents(resolved, path.parent))
        return cls(resolved, before, {}, absent_parents)

    def track(self, *paths: Path) -> None:
        for path in paths:
            if is_link_like(path):
                continue
            if path not in self.before:
                self.before[path] = _snapshot(path)
                self.absent_parents.update(_absent_parents(self.root, path.parent))

    def mark_written(self, *paths: Path) -> None:
        """Record direct writes so later concurrent edits are not overwritten."""
        for path in paths:
            self.written[path] = path.read_bytes() if path.is_file() else None

    def rollback(self) -> RollbackReport:
        issues: list[RollbackIssue] = []
        for path, snapshot in self.before.items():
            expected = self.written.get(path, _UNTRACKED)
            issue = _restore_path(self.root, path, snapshot, expected)
            if issue is not None:
                issues.append(issue)
        for parent in sorted(self.absent_parents, key=lambda item: len(item.parts), reverse=True):
            try:
                parent.rmdir()
            except FileNotFoundError:
                continue
            except OSError:
                # A non-empty directory contains state the transaction does not own.
                continue
        return RollbackReport(tuple(issues))


class _Untracked:
    """Sentinel type for paths without a recorded standards write."""


_UNTRACKED: Final = _Untracked()


def _snapshot(path: Path) -> FileSnapshot:
    if not path.is_file():
        return FileSnapshot(None, None)
    metadata = path.stat(follow_symlinks=False)
    return FileSnapshot(path.read_bytes(), stat.S_IMODE(metadata.st_mode))


def _restore_path(
    root: Path,
    path: Path,
    snapshot: FileSnapshot,
    expected: bytes | _Untracked | None,
) -> RollbackIssue | None:
    try:
        validate_targets(root, (path,))
        current = path.read_bytes() if path.is_file() else None
    except OSError as exc:
        return RollbackIssue(path, str(exc))
    if not isinstance(expected, _Untracked) and current != expected:
        return RollbackIssue(path, "changed concurrently after the standards write")
    try:
        _apply_snapshot(root, path, snapshot)
    except OSError as exc:
        return RollbackIssue(path, str(exc))
    return None


def _apply_snapshot(root: Path, path: Path, snapshot: FileSnapshot) -> None:
    if snapshot.contents is None:
        if path.is_file() or is_link_like(path):
            path.unlink()
        return
    atomic_write_bytes(root, path, snapshot.contents)
    if snapshot.mode is not None:
        path.chmod(snapshot.mode)


def _absent_parents(root: Path, parent: Path) -> set[Path]:
    missing: set[Path] = set()
    current = parent
    while current != root and current.is_relative_to(root):
        if current.exists():
            break
        missing.add(current)
        current = current.parent
    return missing
