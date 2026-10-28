from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, final

from sarj_rule_contracts import SourceSnapshot

from sarj_python_lint._source import decode_python_source


if TYPE_CHECKING:
    from sarj_rule_contracts import SourceCatalog


LOCAL_MODULE_MAX_BYTES = 256_000
type ResolutionKey = tuple[Path, str | None, int]


# The sealed worker needs an observation available only to the parent.
class NeedsSerialSourceError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CapturedSource:
    # Larger project units keep their text and actual byte size on the wire;
    # local analysis must decline them without a second full raw body.
    path: Path
    raw_size: int
    snapshot: SourceSnapshot | None = field(default=None, repr=False)

    @classmethod
    def from_snapshot(cls, snapshot: SourceSnapshot) -> CapturedSource:
        size = len(snapshot.raw)
        return cls(snapshot.path, size, snapshot if size <= LOCAL_MODULE_MAX_BYTES else None)


@dataclass(frozen=True, slots=True)
class PreparedSourceSnapshot:
    entries: tuple[tuple[Path, CapturedSource], ...]
    selected: tuple[tuple[Path, CapturedSource], ...]
    conflicts: frozenset[Path]
    resolutions: tuple[tuple[ResolutionKey, Path | None], ...]
    failed_modules: frozenset[Path]

    @property
    def eligible_raw_count(self) -> int:
        return len({id(entry.snapshot) for _, entry in (*self.entries, *self.selected) if entry.snapshot is not None})

    @property
    def raw_bytes(self) -> int:
        snapshots = {
            id(entry.snapshot): entry.snapshot
            for _, entry in (*self.entries, *self.selected)
            if entry.snapshot is not None
        }
        return sum(len(snapshot.raw) for snapshot in snapshots.values())


@final
class PreparedSourceInputs:
    def __init__(self, catalog: SourceCatalog | None = None, *, sealed: bool = False) -> None:
        self._catalog = catalog
        self.sealed = sealed
        self._entries: dict[Path, CapturedSource] = {}
        self._selected: dict[Path, CapturedSource] = {}
        self._conflicts: set[Path] = set()
        self._resolutions: dict[ResolutionKey, Path | None] = {}
        self._failed_modules: set[Path] = set()

    def remember_selected(self, path: Path, snapshot: SourceSnapshot) -> None:
        captured = CapturedSource.from_snapshot(snapshot)
        self._selected[path] = captured
        self.remember(path, captured)

    def selected_capture(self, path: Path) -> CapturedSource | None:
        return self._selected.get(path)

    def selected_text(self, path: Path) -> str:
        captured = self._selected.get(path)
        if captured is None or captured.snapshot is None:
            raise NeedsSerialSourceError
        try:
            return decode_python_source(captured.snapshot)
        except UnicodeError, SyntaxError:
            raise NeedsSerialSourceError from None

    def remember(self, path: Path, captured: CapturedSource) -> None:
        if self.sealed:
            raise NeedsSerialSourceError
        previous = self._entries.get(path)
        if previous is None:
            self._entries[path] = captured
        elif previous is not captured and not self._same_bytes(previous, captured):
            self._conflicts.add(path)

    def _same_bytes(self, first: CapturedSource, second: CapturedSource) -> bool:
        left = self._body(first)
        right = self._body(second)
        return left is not None and right is not None and left.raw == right.raw

    def _body(self, captured: CapturedSource) -> SourceSnapshot | None:
        if captured.snapshot is not None:
            return captured.snapshot
        return None if self._catalog is None else self._catalog.get(captured.path)

    def associate_selected(self, original: Path, prepared: Path) -> CapturedSource | None:
        captured = self._selected.get(original)
        if captured is not None:
            self.remember(prepared, captured)
        return captured

    def project_snapshot(self, path: Path) -> SourceSnapshot | None:
        if path in self._conflicts:
            return None
        captured = self._entries.get(path)
        return None if captured is None else self._body(captured)

    def module_snapshot(self, path: Path) -> SourceSnapshot | None:
        if path not in self._conflicts:
            captured = self._entries.get(path)
            if captured is not None:
                if captured.raw_size > LOCAL_MODULE_MAX_BYTES:
                    return None
                if captured.snapshot is not None:
                    return captured.snapshot
            if path in self._failed_modules:
                return None
        if self.sealed:
            raise NeedsSerialSourceError
        # Unknown/conflicting byte views retain the parent's legacy bounded read.
        with path.open("rb") as stream:
            raw = stream.read(LOCAL_MODULE_MAX_BYTES + 1)
        if len(raw) > LOCAL_MODULE_MAX_BYTES:
            return None
        return SourceSnapshot(path, raw)

    def remember_module(self, path: Path, snapshot: SourceSnapshot) -> None:
        # Called only after the local decoder and parser have admitted a module.
        if not self.sealed and path not in self._conflicts:
            self.remember(path, CapturedSource.from_snapshot(snapshot))

    def record_failure(self, path: Path) -> None:
        if not self.sealed and path not in self._entries and path not in self._conflicts:
            self._failed_modules.add(path)

    def resolution(self, key: ResolutionKey) -> Path | None:
        if key not in self._resolutions:
            raise NeedsSerialSourceError
        return self._resolutions[key]

    def record_resolution(self, key: ResolutionKey, result: Path | None) -> None:
        if self.sealed:
            raise NeedsSerialSourceError
        self._resolutions[key] = result

    def source_snapshot(self) -> PreparedSourceSnapshot:
        return PreparedSourceSnapshot(
            tuple(self._entries.items()),
            tuple(self._selected.items()),
            frozenset(self._conflicts),
            tuple(self._resolutions.items()),
            frozenset(self._failed_modules),
        )

    @classmethod
    def from_source_snapshot(cls, snapshot: PreparedSourceSnapshot) -> PreparedSourceInputs:
        inputs = cls(sealed=True)
        inputs._entries = dict(snapshot.entries)
        inputs._selected = dict(snapshot.selected)
        inputs._conflicts = set(snapshot.conflicts)
        inputs._resolutions = dict(snapshot.resolutions)
        inputs._failed_modules = set(snapshot.failed_modules)
        return inputs
