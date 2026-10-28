from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, final

from sarj_python_lint._prepared_sources import LOCAL_MODULE_MAX_BYTES, NeedsSerialSourceError
from sarj_python_lint._source import python_source_encoding
from sarj_python_lint.rules._imports import ImportIndex


if TYPE_CHECKING:
    from sarj_python_lint._prepared_sources import PreparedSourceInputs
    from sarj_python_lint.rules._first_party import FirstPartyFacts


_MAX_ANCESTORS = 24
_MAX_MODULE_BYTES = LOCAL_MODULE_MAX_BYTES
LOCAL_SOURCE_CACHE_LIMIT = 512


@dataclass(frozen=True, slots=True)
class LocalModule:
    path: Path
    source: str
    tree: ast.Module
    runtime_imports: ImportIndex


@dataclass(frozen=True, slots=True)
class LocalSourceKeys:
    resolutions: frozenset[tuple[Path, str | None, int]]
    modules: frozenset[Path]


@final
class LocalSourceFacts:
    def __init__(self, *, source_inputs: PreparedSourceInputs | None = None) -> None:
        self._source_inputs = source_inputs
        self._resolutions: dict[tuple[Path, str | None, int], Path | None] = {}
        self._modules: dict[Path, LocalModule | None] = {}

    def resolve_module(self, current: Path, module: str | None, level: int, *, facts: FirstPartyFacts) -> Path | None:
        try:
            current = current.absolute()
        except OSError:
            return None
        key = (current, module, level)
        if key in self._resolutions:
            return self._resolutions[key]
        if len(self._resolutions) >= LOCAL_SOURCE_CACHE_LIMIT:
            return None
        if self._source_inputs is not None and self._source_inputs.sealed:
            result = self._source_inputs.resolution(key)
        else:
            result = _resolve_module(current, module, level, facts=facts)
            if self._source_inputs is not None:
                self._source_inputs.record_resolution(key, result)
        self._resolutions[key] = result
        return result

    def read_module(self, path: Path) -> LocalModule | None:
        if path in self._modules:
            return self._modules[path]
        if len(self._modules) >= LOCAL_SOURCE_CACHE_LIMIT:
            return None
        module = _read_module(path, source_inputs=self._source_inputs)
        if module is None and self._source_inputs is not None:
            self._source_inputs.record_failure(path)
        self._modules[path] = module
        return module

    def cache_keys(self) -> LocalSourceKeys:
        # Failed lookups consume the same semantic budgets as successful ones.
        return LocalSourceKeys(frozenset(self._resolutions), frozenset(self._modules))


def _resolve_module(current: Path, module: str | None, level: int, *, facts: FirstPartyFacts) -> Path | None:
    if ".." in current.parts or level > _MAX_ANCESTORS:
        return None
    root = facts.project_root(current)
    if root is None or not _safe_path(current, root):
        return None
    parts = module.split(".") if module else []
    if any(not part.isidentifier() for part in parts):
        return None
    candidates: set[Path] = set()
    for base in _import_bases(current, root, level):
        target = base.joinpath(*parts)
        for candidate in (target.with_suffix(".py"), target / "__init__.py"):
            if _safe_path(candidate, root) and candidate.is_file():
                candidates.add(candidate)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _import_bases(current: Path, root: Path, level: int) -> list[Path]:
    if level:
        base = current.parent
        for _ in range(level - 1):
            if base == root:
                return []
            base = base.parent
        return [base]
    bases: list[Path] = []
    for ancestor in list(current.parents)[:_MAX_ANCESTORS]:
        if not ancestor.is_relative_to(root):
            break
        bases.append(ancestor)
        if (ancestor / "pyproject.toml").is_file():
            bases.append(ancestor / "src")
        if ancestor == root:
            break
    return bases


def _safe_path(path: Path, root: Path) -> bool:
    if not path.is_relative_to(root):
        return False
    try:
        for entry in (path, *list(path.parents)[:_MAX_ANCESTORS]):
            if entry == root:
                return True
            if entry.is_symlink() or (entry != path and (entry / ".git").exists()):
                return False
    except OSError:
        return False
    return False


def _read_module(path: Path, *, source_inputs: PreparedSourceInputs | None = None) -> LocalModule | None:
    snapshot = None
    if source_inputs is None:
        try:
            with path.open("rb") as stream:
                data = stream.read(_MAX_MODULE_BYTES + 1)
        except OSError, UnicodeError, SyntaxError:
            return None
    else:
        try:
            snapshot = source_inputs.module_snapshot(path)
        except OSError, UnicodeError, SyntaxError:
            return None
        if snapshot is None:
            return None
        data = snapshot.raw
    if len(data) > _MAX_MODULE_BYTES:
        return None
    try:
        source = data.decode(python_source_encoding(data))
    except UnicodeError, SyntaxError:
        if source_inputs is not None and source_inputs.sealed:
            raise NeedsSerialSourceError from None
        return None
    except OSError:
        return None
    try:
        tree = ast.parse(source, filename=str(path))
    except OSError, UnicodeError, SyntaxError:
        return None
    runtime_imports = ast.Module(
        body=[node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))], type_ignores=[]
    )
    if source_inputs is not None and snapshot is not None:
        source_inputs.remember_module(path, snapshot)
    return LocalModule(path, source, tree, ImportIndex.from_tree(runtime_imports))
