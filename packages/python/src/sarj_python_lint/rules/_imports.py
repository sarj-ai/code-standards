from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Self


@dataclass(frozen=True, slots=True)
class _ImportTarget:
    module: str
    symbol: str | None


@dataclass(frozen=True, slots=True)
class ImportIndex:
    bindings: Mapping[str, _ImportTarget]
    shadowed_names: frozenset[str]

    @classmethod
    def from_tree(cls, tree: ast.Module, *, module_scope_only: bool = False) -> Self:
        candidates: dict[str, set[_ImportTarget]] = {}
        statements = _module_import_statements(tree) if module_scope_only else tree.body
        for statement in statements:
            match statement:
                case ast.Import(names=names):
                    for alias in names:
                        local = alias.asname or alias.name.partition(".")[0]
                        module = alias.name if alias.asname else alias.name.partition(".")[0]
                        candidates.setdefault(local, set()).add(_ImportTarget(module, None))
                case ast.ImportFrom(module=str(module), names=names, level=0):
                    for alias in names:
                        if alias.name == "*":
                            continue
                        local = alias.asname or alias.name
                        candidates.setdefault(local, set()).add(_ImportTarget(module, alias.name))
                case _:
                    pass

        imported_names = frozenset(candidates)
        non_import_bindings = (
            _module_non_import_bindings(tree) if module_scope_only else _non_import_bindings(tree)
        )
        rebound = non_import_bindings & imported_names
        bindings = {
            local: next(iter(targets))
            for local, targets in candidates.items()
            if len(targets) == 1 and local not in rebound
        }
        return cls(MappingProxyType(bindings), frozenset(non_import_bindings))

    def resolves(self, node: ast.expr, *, sources: frozenset[str], symbol: str) -> bool:
        resolved = self._resolve(node)
        return resolved is not None and resolved.module in sources and resolved.symbol == symbol

    def resolved_symbol(self, node: ast.expr, *, sources: frozenset[str]) -> str | None:
        resolved = self._resolve(node)
        if resolved is None or resolved.module not in sources:
            return None
        return resolved.symbol

    def builtin_is_unshadowed(self, name: str) -> bool:
        return name not in self.shadowed_names and name not in self.bindings

    def _resolve(self, node: ast.expr) -> _ImportTarget | None:
        match node:
            case ast.Name(id=local):
                target = self.bindings.get(local)
                return target if target is not None and target.symbol is not None else None
            case ast.Attribute():
                parts: list[str] = []
                current: ast.expr = node
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value
                if not isinstance(current, ast.Name):
                    return None
                target = self.bindings.get(current.id)
                if target is None or target.symbol is not None or not parts:
                    return None
                ordered = list(reversed(parts))
                return _ImportTarget(".".join((target.module, *ordered[:-1])), ordered[-1])
            case _:
                return None


def _non_import_bindings(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Name(id=name, ctx=(ast.Store() | ast.Del())) | ast.arg(arg=name):
                names.add(name)
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.add(node.name)
            case ast.alias():
                # Imports are the candidate bindings, not shadows of themselves.
                continue
            case _:
                pass
    return names


def _module_non_import_bindings(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for statement in tree.body:
        match statement:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.add(statement.name)
            case ast.Assign(targets=targets):
                for target in targets:
                    names.update(_target_names(target))
            case ast.AnnAssign(target=target) | ast.AugAssign(target=target):
                names.update(_target_names(target))
            case ast.TypeAlias(name=ast.Name(id=name)):
                names.add(name)
            case ast.Import() | ast.ImportFrom():
                continue
            case _:
                # Module control flow can still bind names in the module namespace.
                _collect_module_bindings(statement, names)
    return names


def _target_names(node: ast.expr) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {name for element in node.elts for name in _target_names(element)}
    return set()


def _collect_module_bindings(node: ast.AST, names: set[str]) -> None:
    match node:
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
            names.add(node.name)
            return
        case ast.ListComp() | ast.SetComp() | ast.GeneratorExp():
            _collect_module_bindings(node.elt, names)
            _collect_comprehension_bindings(node.generators, names)
            return
        case ast.DictComp():
            _collect_module_bindings(node.key, names)
            _collect_module_bindings(node.value, names)
            _collect_comprehension_bindings(node.generators, names)
            return
        case ast.Lambda():
            return
        case ast.Name(id=name, ctx=(ast.Store() | ast.Del())):
            names.add(name)
        case _:
            pass
    for child in ast.iter_child_nodes(node):
        _collect_module_bindings(child, names)


def _collect_comprehension_bindings(generators: list[ast.comprehension], names: set[str]) -> None:
    for generator in generators:
        _collect_module_bindings(generator.iter, names)
        for condition in generator.ifs:
            _collect_module_bindings(condition, names)


def _module_import_statements(tree: ast.Module) -> list[ast.stmt]:
    statements = list(tree.body)
    for statement in tree.body:
        if not isinstance(statement, ast.If) or not _is_type_checking_guard(statement.test):
            continue
        statements.extend(
            child for child in statement.body if isinstance(child, (ast.Import, ast.ImportFrom))
        )
    return statements


def _is_type_checking_guard(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING") or (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id in {"typing", "typing_extensions"}
        and node.attr == "TYPE_CHECKING"
    )
