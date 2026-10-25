from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tempfile
from typing import Final, Self

from sarj_rule_contracts import fix_file

from sarj_standards.libs.filesystem import is_link_like


_OWNED_NAMES: Final = frozenset(
    {
        ".pre-commit-config.yaml",
        ".pre-commit-config.yml",
        ".sarj-standards.toml",
        ".ruff-strict.toml",
        ".pyright-strict.json",
        ".basedpyright-strict.json",
        "pyright.strict.json",
        ".markdownlint.yaml",
        ".taplo.toml",
        ".yamllint.yaml",
        "eslint.config.js",
        "eslint.config.mjs",
        "eslint.config.cjs",
        "eslint.config.ts",
        "eslint.config.mts",
        "eslint.config.cts",
        "eslint.strict.mjs",
        "eslint.strict.ts",
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
    atomic_write_bytes(root, path, contents.encode("utf-8"))


def atomic_write_bytes(root: Path, path: Path, contents: bytes, *, mode: int | None = None) -> None:
    validate_targets(root, (path,))
    path.parent.mkdir(parents=True, exist_ok=True)
    validate_targets(root, (path,))
    if mode is None:
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
    validate_targets(root, (path,))
    current = path.read_bytes() if path.is_file() else None
    if current != expected:
        msg = f"planned mutation target changed concurrently: {path}; rerun the command"
        raise OSError(msg)


def remove_file(root: Path, path: Path) -> None:
    validate_targets(root, (path,))
    try:
        path.unlink()
    except FileNotFoundError as exc:
        msg = f"planned deletion target changed concurrently: {path}; rerun the command"
        raise OSError(msg) from exc


def _write_temporary(descriptor: int, contents: bytes, mode: int) -> None:
    with os.fdopen(descriptor, "wb") as handle:
        os.fchmod(handle.fileno(), mode)
        handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())


@dataclass
class FileSnapshot:
    contents: bytes | None
    mode: int | None
    group: int | None = None


@dataclass(frozen=True, slots=True)
class RollbackIssue:
    path: Path
    detail: str


@dataclass(frozen=True, slots=True)
class RollbackReport:
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
    root: Path
    before: dict[Path, FileSnapshot]
    written: dict[Path, bytes | None]
    absent_parents: set[Path]
    explicit_only: bool = False
    source_writes: bool = False

    @classmethod
    def capture(
        cls, root: Path, extra: tuple[Path, ...] = (), *, explicit_only: bool = False, source_writes: bool = False
    ) -> Self:
        resolved = root.resolve()
        if source_writes:
            if not explicit_only:
                msg = "source transactions require explicit mutation targets"
                raise ValueError(msg)
            validate_targets(resolved, extra)
        candidates = set(extra) if explicit_only else _capture_candidates(resolved, extra)
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
            before[path] = _snapshot(path, source_write=source_writes)
            absent_parents.update(_absent_parents(resolved, path.parent))
        if source_writes and any(snapshot.contents is None for snapshot in before.values()):
            msg = "source transactions require existing regular files"
            raise OSError(msg)
        return cls(resolved, before, {}, absent_parents, explicit_only, source_writes)

    def write_text(self, path: Path, contents: str) -> None:
        self.write_bytes(path, contents.encode("utf-8"))

    def write_bytes(self, path: Path, contents: bytes) -> None:
        snapshot = self.before[path]
        assert_expected(self.root, path, self.written.get(path, snapshot.contents))
        if self.source_writes:
            _write_source(
                self.root, path, contents, expected=self.written.get(path, snapshot.contents), snapshot=snapshot
            )
        else:
            atomic_write_bytes(self.root, path, contents)
        self.written[path] = contents

    def track(self, *paths: Path) -> None:
        for path in paths:
            if is_link_like(path):
                continue
            if path not in self.before:
                self.before[path] = _snapshot(path, source_write=self.source_writes)
                self.absent_parents.update(_absent_parents(self.root, path.parent))

    def mark_written(self, *paths: Path) -> None:
        for path in paths:
            self.written[path] = path.read_bytes() if path.is_file() else None

    def rollback(self) -> RollbackReport:
        issues: list[RollbackIssue] = []
        for path, snapshot in self.before.items():
            if self.explicit_only and path not in self.written:
                continue
            expected = self.written.get(path, _UNTRACKED)
            issue = _restore_path(self.root, path, snapshot, expected, source_write=self.source_writes)
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


def _snapshot(path: Path, *, source_write: bool = False) -> FileSnapshot:
    if not path.is_file():
        return FileSnapshot(None, None)
    metadata = path.stat(follow_symlinks=False)
    return FileSnapshot(path.read_bytes(), stat.S_IMODE(metadata.st_mode), metadata.st_gid if source_write else None)


def _restore_path(
    root: Path,
    path: Path,
    snapshot: FileSnapshot,
    expected: bytes | _Untracked | None,
    *,
    source_write: bool = False,
) -> RollbackIssue | None:
    try:
        validate_targets(root, (path,))
        current = path.read_bytes() if path.is_file() else None
    except OSError as exc:
        return RollbackIssue(path, str(exc))
    if not isinstance(expected, _Untracked) and current != expected:
        return RollbackIssue(path, "changed concurrently after the standards write")
    try:
        if source_write:
            _restore_source(root, path, snapshot, expected)
        else:
            _apply_snapshot(root, path, snapshot)
    except (OSError, ValueError) as exc:
        return RollbackIssue(path, str(exc))
    return None


def _restore_source(
    root: Path,
    path: Path,
    snapshot: FileSnapshot,
    expected: bytes | _Untracked | None,
) -> None:
    if snapshot.contents is None or isinstance(expected, _Untracked):
        msg = "source rollback requires an owned existing-file write"
        raise OSError(msg)
    _write_source(root, path, snapshot.contents, expected=expected, snapshot=snapshot)


def _write_source(root: Path, path: Path, contents: bytes, *, expected: bytes | None, snapshot: FileSnapshot) -> None:
    validate_targets(root, (path,))

    def transform(source: str) -> str:
        if source.encode("latin-1") != expected:
            msg = f"planned mutation target changed concurrently: {path}; rerun the command"
            raise OSError(msg)
        metadata = path.stat(follow_symlinks=False)
        if stat.S_IMODE(metadata.st_mode) != snapshot.mode or metadata.st_gid != snapshot.group:
            msg = f"source permissions or group changed concurrently: {path}; rerun the command"
            raise OSError(msg)
        return contents.decode("latin-1")

    fix_file(path, transform, source_encoding=lambda _raw: "latin-1")


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


def _capture_candidates(resolved: Path, extra: tuple[Path, ...]) -> set[Path]:
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
    return candidates
