from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import os
from pathlib import Path
import stat
import tempfile
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Self, assert_never

from sarj_rule_contracts import SourceChangedError, fix_file

from sarj_standards.libs.filesystem import is_link_like

from .configs import (
    LEGACY_ESLINT_CONFIG_NAMES,
    LEGACY_ESLINT_PRESET_NAMES,
    LEGACY_ESLINT_SUPPRESSIONS,
    OXFMT_ENTRYPOINT,
    OXLINT_ENTRYPOINT,
    OXLINT_PRESET,
    OXLINT_SUPPRESSIONS,
)


if TYPE_CHECKING:
    from collections.abc import Mapping


_OWNED_NAMES: Final = frozenset(
    {
        ".pre-commit-config.yaml",
        ".pre-commit-config.yml",
        ".sarj-standards.toml",
        ".gitattributes",
        ".ruff-strict.toml",
        ".pyright-strict.json",
        ".basedpyright-strict.json",
        "pyright.strict.json",
        ".markdownlint.yaml",
        ".taplo.toml",
        ".yamllint.yaml",
        *LEGACY_ESLINT_CONFIG_NAMES,
        *LEGACY_ESLINT_PRESET_NAMES,
        LEGACY_ESLINT_SUPPRESSIONS,
        OXFMT_ENTRYPOINT,
        "oxfmt.strict.mts",
        OXLINT_ENTRYPOINT,
        OXLINT_PRESET,
        OXLINT_SUPPRESSIONS,
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


@dataclass(frozen=True, slots=True)
class MissingFile:
    kind: ClassVar[Literal["missing"]] = "missing"
    contents: ClassVar[None] = None
    mode: ClassVar[None] = None
    group: ClassVar[None] = None


@dataclass(frozen=True, slots=True)
class ManagedFile:
    kind: ClassVar[Literal["managed"]] = "managed"
    contents: bytes
    mode: int
    group: ClassVar[None] = None


@dataclass(frozen=True, slots=True)
class SourceFile:
    kind: ClassVar[Literal["source"]] = "source"
    contents: bytes
    mode: int
    group: int


type FileSnapshot = MissingFile | ManagedFile | SourceFile


class CaptureMode(StrEnum):
    MANAGED = "managed"
    EXPLICIT = "explicit"
    SOURCE = "source"


@dataclass(frozen=True, slots=True)
class _CapturedFile:
    kind: ClassVar[Literal["captured"]] = "captured"
    snapshot: FileSnapshot


@dataclass(frozen=True, slots=True)
class _PublishedFile:
    kind: ClassVar[Literal["published"]] = "published"
    snapshot: FileSnapshot
    receipt: bytes | None


@dataclass(frozen=True, slots=True)
class _WritingFile:
    kind: ClassVar[Literal["writing"]] = "writing"
    previous: _CapturedFile | _PublishedFile
    intended: bytes | None

    @property
    def snapshot(self) -> FileSnapshot:
        return self.previous.snapshot


type _UnrecoveredFile = _CapturedFile | _PublishedFile | _WritingFile


@dataclass(frozen=True, slots=True)
class _ReleasedFile:
    kind: ClassVar[Literal["released"]] = "released"
    previous: _UnrecoveredFile

    @property
    def snapshot(self) -> FileSnapshot:
        return self.previous.snapshot


type _FileMutation = _UnrecoveredFile | _ReleasedFile


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


class _RecoveryPhase(StrEnum):
    ACTIVE = "active"
    RECOVERING = "recovering"


@dataclass(frozen=True, slots=True)
class _RecoveryComplete:
    kind: ClassVar[Literal["recovered"]] = "recovered"
    report: ClassVar[RollbackReport] = RollbackReport()


type _Recovery = _RecoveryPhase | _RecoveryComplete


@dataclass
class FileTransaction:
    root: Path
    _files: dict[Path, _FileMutation]
    absent_parents: set[Path]
    _mode: CaptureMode
    _recovery: _Recovery = field(init=False, default=_RecoveryPhase.ACTIVE)

    @property
    def before(self) -> Mapping[Path, FileSnapshot]:
        return MappingProxyType({path: state.snapshot for path, state in self._files.items()})

    @property
    def written(self) -> Mapping[Path, bytes | None]:
        receipts: dict[Path, bytes | None] = {}
        for path, state in self._files.items():
            unrecovered = state.previous if isinstance(state, _ReleasedFile) else state
            settled = unrecovered.previous if isinstance(unrecovered, _WritingFile) else unrecovered
            if isinstance(settled, _PublishedFile):
                receipts[path] = settled.receipt
        return MappingProxyType(receipts)

    @classmethod
    def capture(cls, root: Path, extra: tuple[Path, ...] = (), *, mode: CaptureMode = CaptureMode.MANAGED) -> Self:
        resolved = root.resolve()
        mode = CaptureMode(mode)
        if mode is CaptureMode.SOURCE:
            validate_targets(resolved, extra)
        candidates = _capture_candidates(resolved, extra) if mode is CaptureMode.MANAGED else set(extra)
        files: dict[Path, _FileMutation] = {}
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
            files[path] = _CapturedFile(_snapshot(path, mode))
            absent_parents.update(_absent_parents(resolved, path.parent))
        return cls(resolved, files, absent_parents, mode)

    def require_owned_writes(self) -> None:
        self._require_active()
        if self._mode is CaptureMode.MANAGED:
            self._mode = CaptureMode.EXPLICIT

    def allow_installer_mutations(self, paths: tuple[Path, ...]) -> None:
        self._require_active()
        if self._mode is CaptureMode.SOURCE:
            msg = "source transactions cannot delegate installer mutations"
            raise ValueError(msg)
        files = dict(self._files)
        for path in paths:
            state = files[path]
            match state:
                case _WritingFile():
                    msg = "pending mutation must be resolved before starting an installer"
                    raise ValueError(msg)
                case _ReleasedFile():
                    msg = "recovered file cannot be delegated to an installer"
                    raise ValueError(msg)
                case _CapturedFile() | _PublishedFile():
                    files[path] = _CapturedFile(state.snapshot)
                case _:
                    assert_never(state)
        self._mode = CaptureMode.MANAGED
        self._files = files

    def write_text(self, path: Path, contents: str) -> None:
        self.write_bytes(path, contents.encode("utf-8"))

    def write_bytes(self, path: Path, contents: bytes) -> None:
        self._require_active()
        previous = self._settled(path)
        snapshot = previous.snapshot
        expected = previous.receipt if isinstance(previous, _PublishedFile) else snapshot.contents
        assert_expected(self.root, path, expected)
        # A pending attempt does not claim untouched state, but survives interruption after replacement.
        if isinstance(snapshot, SourceFile) and not isinstance(expected, bytes):
            msg = "source transactions require an owned existing-file write"
            raise OSError(msg)
        self._files[path] = _WritingFile(previous, contents)
        if isinstance(snapshot, SourceFile):
            try:
                _write_source(self.root, path, contents, expected=expected, snapshot=snapshot)
            except SourceChangedError:
                # This attempt never replaced the source; retain any earlier successful receipt.
                self._files[path] = previous
                raise
        else:
            atomic_write_bytes(self.root, path, contents)
        self.record_write(path, contents)

    def remove_file(self, path: Path) -> None:
        self._require_active()
        if self._mode is CaptureMode.SOURCE:
            msg = "source transactions do not support file deletion"
            raise ValueError(msg)
        previous = self._settled(path)
        expected = previous.receipt if isinstance(previous, _PublishedFile) else previous.snapshot.contents
        assert_expected(self.root, path, expected)
        self._files[path] = _WritingFile(previous, None)
        remove_file(self.root, path)
        self.record_write(path, None)

    def _settled(self, path: Path) -> _CapturedFile | _PublishedFile:
        state = self._files[path]
        match state:
            case _CapturedFile() | _PublishedFile():
                return state
            case _WritingFile() | _ReleasedFile():
                msg = "pending mutation must be resolved before another write"
                raise ValueError(msg)
            case _:
                assert_never(state)

    def _require_active(self) -> None:
        match self._recovery:
            case _RecoveryPhase.ACTIVE:
                return
            case _RecoveryPhase.RECOVERING | _RecoveryComplete():
                msg = "transaction recovery has begun; capture a new transaction for further writes"
                raise ValueError(msg)
            case _:
                assert_never(self._recovery)

    def track(self, *paths: Path) -> None:
        self._require_active()
        for path in paths:
            if is_link_like(path):
                continue
            if path not in self._files:
                self._files[path] = _CapturedFile(_snapshot(path, self._mode))
                self.absent_parents.update(_absent_parents(self.root, path.parent))

    def mark_written(self, *paths: Path) -> None:
        for path in paths:
            self.record_write(path, path.read_bytes() if path.is_file() else None)

    def record_write(self, path: Path, contents: bytes | None) -> None:
        self._require_active()
        state = self._files[path]
        if isinstance(state, _WritingFile) and contents != state.intended:
            msg = "write acknowledgement differs from its pending mutation"
            raise ValueError(msg)
        if isinstance(state.snapshot, SourceFile) and contents is None:
            msg = "source transactions cannot acknowledge file deletion"
            raise ValueError(msg)
        self._files[path] = _PublishedFile(state.snapshot, contents)

    def rollback(self) -> RollbackReport:
        match self._recovery:
            case _RecoveryComplete():
                return self._recovery.report
            case _RecoveryPhase.ACTIVE | _RecoveryPhase.RECOVERING:
                self._recovery = _RecoveryPhase.RECOVERING
            case _:
                assert_never(self._recovery)
        issues: list[RollbackIssue] = []
        for path, state in self._files.items():
            if isinstance(state, _ReleasedFile):
                continue
            issue = _restore_path(self.root, path, state, self._mode)
            if issue is not None:
                issues.append(issue)
            else:
                self._files[path] = _ReleasedFile(state)
        for parent in sorted(self.absent_parents, key=lambda item: len(item.parts), reverse=True):
            try:
                parent.rmdir()
            except FileNotFoundError:
                continue
            except OSError:
                # A non-empty directory contains state the transaction does not own.
                continue
        report = RollbackReport(tuple(issues))
        if report.ok:
            self._recovery = _RecoveryComplete()
            return self._recovery.report
        return report


class _Untracked:
    pass


_UNTRACKED: Final = _Untracked()


@dataclass(frozen=True, slots=True)
class _RestoreFile:
    expected: bytes | _Untracked | None


def _snapshot(path: Path, mode: CaptureMode) -> FileSnapshot:
    if not path.is_file():
        if mode is CaptureMode.SOURCE:
            msg = "source transactions require existing regular files"
            raise OSError(msg)
        return MissingFile()
    metadata = path.stat(follow_symlinks=False)
    contents = path.read_bytes()
    permissions = stat.S_IMODE(metadata.st_mode)
    return (
        SourceFile(contents, permissions, metadata.st_gid)
        if mode is CaptureMode.SOURCE
        else ManagedFile(contents, permissions)
    )


def _restore_path(
    root: Path,
    path: Path,
    state: _UnrecoveredFile,
    mode: CaptureMode,
) -> RollbackIssue | None:
    if isinstance(state, _CapturedFile) and mode is not CaptureMode.MANAGED:
        return None
    try:
        validate_targets(root, (path,))
        current = path.read_bytes() if path.is_file() else None
    except OSError as exc:
        return RollbackIssue(path, str(exc))
    decision = _restore_decision(path, state, current, mode)
    if not isinstance(decision, _RestoreFile):
        return decision
    try:
        if isinstance(state.snapshot, SourceFile):
            _restore_source(root, path, state.snapshot, decision.expected)
        else:
            _apply_snapshot(root, path, state.snapshot)
    except (OSError, ValueError) as exc:
        return RollbackIssue(path, str(exc))
    return None


def _restore_decision(
    path: Path, state: _UnrecoveredFile, current: bytes | None, mode: CaptureMode
) -> _RestoreFile | RollbackIssue | None:
    settled = state.previous if isinstance(state, _WritingFile) else state
    expected = settled.receipt if isinstance(settled, _PublishedFile) else _UNTRACKED
    if isinstance(state, _WritingFile):
        prior_contents = settled.receipt if isinstance(settled, _PublishedFile) else state.snapshot.contents
        if current == prior_contents:
            if mode is not CaptureMode.MANAGED and isinstance(settled, _CapturedFile):
                return None
        elif current == state.intended:
            expected = state.intended
        else:
            return RollbackIssue(path, "changed concurrently after the standards write")
    if not isinstance(expected, _Untracked) and current != expected:
        return RollbackIssue(path, "changed concurrently after the standards write")
    return _RestoreFile(expected)


def _restore_source(
    root: Path,
    path: Path,
    snapshot: SourceFile,
    expected: bytes | _Untracked | None,
) -> None:
    if not isinstance(expected, bytes):
        msg = "source rollback requires an owned existing-file write"
        raise OSError(msg)
    _write_source(root, path, snapshot.contents, expected=expected, snapshot=snapshot)


def _write_source(root: Path, path: Path, contents: bytes, *, expected: bytes | None, snapshot: SourceFile) -> None:
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
    if isinstance(snapshot, MissingFile):
        if path.is_file() or is_link_like(path):
            path.unlink()
        return
    atomic_write_bytes(root, path, snapshot.contents, mode=snapshot.mode)


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
