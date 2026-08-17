"""Bounded, run-scoped first-party symbol index for project-aware rules."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, final

from sarj_python_lint.rules._first_party import first_party_packages, project_root


if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Self


_SKIP_DIRS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "site-packages",
        "vendor",
        "vendored",
        "venv",
    }
)
_MAX_ROOTS = 8
_MAX_FILES_PER_ROOT = 10_000
_MAX_FILE_BYTES = 500_000
_NEW_TYPE_MIN_ARGS = 2


@dataclass(frozen=True, slots=True)
class SymbolRef:
    module: str
    name: str


@dataclass(frozen=True, slots=True)
class ClassSummary:
    symbol: SymbolRef
    fields: Mapping[str, ast.expr]
    is_enum: bool


@dataclass(frozen=True, slots=True)
class SourceUnit:
    path: Path
    module: str | None
    source: str
    tree: ast.Module | None
    imports: Mapping[str, SymbolRef]


@dataclass(frozen=True, slots=True)
class LoadedSource:
    path: Path
    source: str


@final
class ProjectIndexSet:
    """Immutable summaries for every bounded first-party root in one lint run."""

    def __init__(self, units: Mapping[Path, SourceUnit]) -> None:
        self._units = MappingProxyType(dict(units))
        by_module = {unit.module: unit for unit in units.values() if unit.module is not None}
        self._by_module = MappingProxyType(by_module)
        classes: dict[SymbolRef, ClassSummary] = {}
        nominals: dict[str, set[SymbolRef]] = {}
        for unit in units.values():
            if unit.module is None or unit.tree is None:
                continue
            for statement in unit.tree.body:
                if isinstance(statement, ast.ClassDef):
                    symbol = SymbolRef(unit.module, statement.name)
                    fields = {
                        item.target.id: item.annotation
                        for item in statement.body
                        if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
                    }
                    classes[symbol] = ClassSummary(
                        symbol=symbol,
                        fields=MappingProxyType(fields),
                        is_enum=any(_tail(base) in {"Enum", "IntEnum", "StrEnum"} for base in statement.bases),
                    )
                nominal = _new_type(statement, unit.module)
                if nominal is not None:
                    nominals.setdefault(_field_key(nominal.name), set()).add(nominal)
        self._classes = MappingProxyType(classes)
        self._nominals = MappingProxyType({key: frozenset(value) for key, value in nominals.items()})

    @classmethod
    def build(cls, paths: Sequence[Path], loaded: Mapping[Path, str]) -> Self:
        roots = sorted({root for path in paths if (root := project_root(path)) is not None})[:_MAX_ROOTS]
        package_roots = tuple(package for root in roots for package in first_party_packages(root))
        sources: dict[Path, str] = dict(loaded)
        for root in roots:
            count = 0
            for path in root.rglob("*.py"):
                if count >= _MAX_FILES_PER_ROOT or any(part in _SKIP_DIRS for part in path.parts):
                    continue
                loaded_source = _read_bounded_source(root, path)
                if loaded_source is None:
                    continue
                sources.setdefault(loaded_source.path, loaded_source.source)
                count += 1
        return cls(_units(sources, package_roots))

    @classmethod
    def single(cls, path: Path, source: str) -> Self:
        return cls(_units({path: source}))

    def unit(self, path: Path) -> SourceUnit | None:
        direct = self._units.get(path)
        if direct is not None:
            return direct
        try:
            return self._units.get(path.resolve())
        except OSError:
            return None

    def nominal_for_field(self, name: str) -> SymbolRef | None:
        matches = self._nominals.get(name)
        return next(iter(matches)) if matches is not None and len(matches) == 1 else None

    @staticmethod
    def resolve(unit: SourceUnit, expression: ast.expr) -> SymbolRef | None:
        if unit.module is None:
            return None
        if isinstance(expression, ast.Name):
            return unit.imports.get(expression.id) or SymbolRef(unit.module, expression.id)
        if isinstance(expression, ast.Attribute) and isinstance(expression.value, ast.Name):
            root = unit.imports.get(expression.value.id)
            if root is not None:
                return SymbolRef(root.module, expression.attr) if not root.name else None
        return None

    def class_for(self, unit: SourceUnit, expression: ast.expr) -> ClassSummary | None:
        symbol = self.resolve(unit, expression)
        return self._classes.get(symbol) if symbol is not None else None

    def annotation_contains_enum(self, unit: SourceUnit, annotation: ast.expr) -> bool:
        for member in ast.walk(annotation):
            if not isinstance(member, (ast.Name, ast.Attribute)):
                continue
            symbol = self.resolve(unit, member)
            summary = self._classes.get(symbol) if symbol is not None else None
            if summary is not None and summary.is_enum:
                return True
        return False

    def source_unit(self, module: str) -> SourceUnit | None:
        return self._by_module.get(module)


def _units(sources: Mapping[Path, str], package_roots: Sequence[tuple[str, Path]] = ()) -> dict[Path, SourceUnit]:
    parsed: dict[Path, tuple[str | None, str, ast.Module | None]] = {}
    for path, source in sources.items():
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            tree = None
        parsed[path] = (_module_name(path, package_roots), source, tree)
    return {
        path: SourceUnit(
            path=path,
            module=module,
            source=source,
            tree=tree,
            imports=MappingProxyType(_imports(module, tree, is_package=path.name == "__init__.py")),
        )
        for path, (module, source, tree) in parsed.items()
    }


def _module_name(path: Path, package_roots: Sequence[tuple[str, Path]]) -> str | None:
    resolved = path.resolve()
    for package_name, package_dir in sorted(package_roots, key=lambda item: len(item[1].parts), reverse=True):
        try:
            relative = resolved.relative_to(package_dir.resolve())
        except OSError, ValueError:
            continue
        suffix = relative.parts[:-1] if relative.name == "__init__.py" else (*relative.parts[:-1], relative.stem)
        return ".".join((package_name, *suffix))
    parts: list[str] = []
    parent = path.parent
    try:
        while (parent / "__init__.py").is_file():
            parts.append(parent.name)
            parent = parent.parent
    except OSError:
        return None
    if not parts:
        if path.is_absolute():
            return None
        relative = [part for part in path.parts if part not in {".", ".."}]
        if not relative:
            return None
        if path.name == "__init__.py":
            return ".".join(relative[:-1]) or None
        return ".".join([*relative[:-1], path.stem])
    parts.reverse()
    if path.name != "__init__.py":
        parts.append(path.stem)
    return ".".join(parts)


def _imports(module: str | None, tree: ast.Module | None, *, is_package: bool) -> dict[str, SymbolRef]:
    if module is None or tree is None:
        return {}
    result: dict[str, SymbolRef] = {}
    package = module if is_package else module.rpartition(".")[0]
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and not any(alias.name == "*" for alias in node.names):
            target = _relative_module(package, node.level, node.module)
            if target is None:
                continue
            for alias in node.names:
                result[alias.asname or alias.name] = SymbolRef(target, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    result[alias.asname] = SymbolRef(alias.name, "")
    return result


def _relative_module(package: str, level: int, module: str | None) -> str | None:
    if level == 0:
        return module
    parts = package.split(".") if package else []
    if level > len(parts) + 1:
        return None
    base = parts[: len(parts) - level + 1]
    if module:
        base.extend(module.split("."))
    return ".".join(base) if base else None


def _new_type(statement: ast.stmt, module: str) -> SymbolRef | None:
    target: ast.Name | None = None
    value: ast.expr | None = None
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        target, value = statement.targets[0], statement.value
    elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        target, value = statement.target, statement.value
    if (
        target is None
        or not isinstance(value, ast.Call)
        or _tail(value.func) != "NewType"
        or len(value.args) < _NEW_TYPE_MIN_ARGS
    ):
        return None
    declared = value.args[0]
    carrier = value.args[1]
    if not (
        isinstance(declared, ast.Constant) and declared.value == target.id and _tail(carrier) in {"UUID", "int", "str"}
    ):
        return None
    return SymbolRef(module, target.id)


def _field_key(type_name: str) -> str:
    first = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", type_name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first).lower()


def _tail(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _read_bounded_source(root: Path, path: Path) -> LoadedSource | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            return None
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
        return LoadedSource(resolved, resolved.read_text(encoding="utf-8", errors="replace"))
    except OSError, ValueError:
        return None
