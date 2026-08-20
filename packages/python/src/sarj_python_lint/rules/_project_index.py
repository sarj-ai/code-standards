from __future__ import annotations

import ast
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
import os
from pathlib import Path
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, final

from sarj_python_lint.rules._first_party import FirstPartyFacts, project_root


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
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
_MAX_DIRS_PER_ROOT = 3_000
_MAX_FILES_PER_ROOT = 10_000
_MAX_FILE_BYTES = 500_000
_MAX_SOURCE_CHARS_PER_ROOT = 50_000_000
_NEW_TYPE_MIN_ARGS = 2
_MATCH_CLASS_RE: re.Pattern[str] = re.compile(r"\bcase\s+([A-Z][A-Za-z0-9_]*)\s*\(")


@dataclass(frozen=True, slots=True)
class SymbolRef:
    module: str
    name: str


@dataclass(frozen=True, slots=True)
class ClassSummary:
    symbol: SymbolRef
    fields: Mapping[str, ast.expr]
    bases: tuple[SymbolRef, ...]
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
                        bases=tuple(
                            resolved
                            for base in statement.bases
                            if (resolved := _resolve(unit, base.value if isinstance(base, ast.Subscript) else base))
                            is not None
                        ),
                        is_enum=any(_tail(base) in {"Enum", "IntEnum", "StrEnum"} for base in statement.bases),
                    )
                nominal = _new_type(statement, unit.module)
                if nominal is not None:
                    nominals.setdefault(_field_key(nominal.name), set()).add(nominal)
        self._classes = MappingProxyType(classes)
        self._nominals = MappingProxyType({key: frozenset(value) for key, value in nominals.items()})

    @classmethod
    def build(
        cls,
        paths: Sequence[Path],
        loaded: Mapping[Path, str],
        *,
        facts: FirstPartyFacts | None = None,
    ) -> Self:
        roots = _project_roots(paths, facts=facts)
        sources: dict[Path, str] = {}
        for path, source in loaded.items():
            try:
                sources[path.resolve()] = source
            except OSError:
                continue
        for root in roots:
            count = 0
            source_chars = 0
            for path in _python_files(root):
                if count >= _MAX_FILES_PER_ROOT or source_chars >= _MAX_SOURCE_CHARS_PER_ROOT:
                    break
                try:
                    if path.resolve() in sources:
                        count += 1
                        continue
                except OSError:
                    continue
                loaded_source = _read_bounded_source(root, path)
                if loaded_source is None:
                    continue
                if source_chars + len(loaded_source.source) > _MAX_SOURCE_CHARS_PER_ROOT:
                    break
                sources.setdefault(loaded_source.path, loaded_source.source)
                source_chars += len(loaded_source.source)
                count += 1
        return cls(_units(sources, roots))

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

    def class_inherits_from(self, unit: SourceUnit, name: str, qualified_bases: frozenset[str]) -> bool:
        if unit.module is None:
            return False
        pending = [SymbolRef(unit.module, name)]
        seen: set[SymbolRef] = set()
        while pending:
            symbol = pending.pop()
            if symbol in seen:
                continue
            seen.add(symbol)
            summary = self._classes.get(symbol)
            if summary is None:
                continue
            for base in summary.bases:
                if f"{base.module}.{base.name}" in qualified_bases:
                    return True
                pending.append(base)
        return False


def _units(sources: Mapping[Path, str], roots: Sequence[Path] = ()) -> dict[Path, SourceUnit]:
    matched_classes = {
        match.group(1)
        for source in sources.values()
        if "match " in source and "str(" in source
        for match in _MATCH_CLASS_RE.finditer(source)
    }
    parsed: dict[Path, tuple[str | None, str, ast.Module | None]] = {}
    for path, source in sources.items():
        if not _is_index_candidate(source, matched_classes):
            continue
        tree: ast.Module | None = None
        with suppress(SyntaxError):
            tree = ast.parse(source, filename=str(path))
        parsed[path] = (_module_name(path, roots), source, tree)
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


def _is_index_candidate(source: str, matched_classes: set[str]) -> bool:
    return (
        "NewType(" in source
        or "class " in source
        or ("match " in source and "str(" in source)
        or any(f"class {name}" in source for name in matched_classes)
    )


def _module_name(path: Path, roots: Sequence[Path]) -> str | None:
    resolved = path.resolve()
    root = next((candidate for candidate in roots if resolved == candidate or candidate in resolved.parents), None)
    if root is not None:
        package_dir: Path | None = None
        for ancestor in resolved.parents:
            if ancestor == root:
                break
            try:
                if (ancestor / "__init__.py").is_file():
                    package_dir = ancestor
            except OSError:
                return None
        if package_dir is not None:
            relative = resolved.relative_to(package_dir)
            suffix = relative.parts[:-1] if relative.name == "__init__.py" else (*relative.parts[:-1], relative.stem)
            return ".".join((package_dir.name, *suffix))
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


def _project_roots(paths: Sequence[Path], *, facts: FirstPartyFacts | None = None) -> tuple[Path, ...]:
    candidates: set[Path] = set()
    for path in paths:
        try:
            root = project_root(path.resolve(), facts=facts)
        except OSError:
            continue
        if root is not None:
            candidates.add(root)
    roots: list[Path] = []
    for candidate in sorted(candidates):
        if any(candidate == root or root in candidate.parents for root in roots):
            continue
        roots.append(candidate)
        if len(roots) >= _MAX_ROOTS:
            break
    return tuple(roots)


def _python_files(root: Path) -> Iterator[Path]:
    for scanned, (directory, dir_names, file_names) in enumerate(os.walk(root), start=1):
        if scanned > _MAX_DIRS_PER_ROOT:
            return
        parent = Path(directory)
        dir_names[:] = [
            name
            for name in sorted(dir_names)
            if not name.startswith(".") and name not in _SKIP_DIRS and not (parent / name / ".git").exists()
        ]
        for name in sorted(file_names):
            if name.endswith(".py"):
                yield parent / name


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
                local_name = alias.asname or alias.name.partition(".")[0]
                module = alias.name if alias.asname else local_name
                result[local_name] = SymbolRef(module, "")
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
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return ""


def _resolve(unit: SourceUnit, expression: ast.expr) -> SymbolRef | None:
    if unit.module is None:
        return None
    if isinstance(expression, ast.Name):
        return unit.imports.get(expression.id) or SymbolRef(unit.module, expression.id)
    if isinstance(expression, ast.Attribute) and isinstance(expression.value, ast.Name):
        root = unit.imports.get(expression.value.id)
        if root is not None and not root.name:
            return SymbolRef(root.module, expression.attr)
    return None


def _read_bounded_source(root: Path, path: Path) -> LoadedSource | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
            return None
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
        return LoadedSource(resolved, resolved.read_text(encoding="utf-8", errors="replace"))
    except OSError, ValueError:
        return None
