"""Conservative module-import resolution for syntax-aware rules."""

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
    """Unambiguous imports whose local bindings are never reassigned."""

    bindings: Mapping[str, _ImportTarget]
    shadowed_names: frozenset[str]

    @classmethod
    def from_tree(cls, tree: ast.Module) -> Self:
        candidates: dict[str, list[_ImportTarget]] = {}
        for statement in tree.body:
            match statement:
                case ast.Import(names=names):
                    for alias in names:
                        local = alias.asname or alias.name.partition(".")[0]
                        module = alias.name if alias.asname else alias.name.partition(".")[0]
                        candidates.setdefault(local, []).append(_ImportTarget(module, None))
                case ast.ImportFrom(module=str(module), names=names, level=0):
                    for alias in names:
                        if alias.name == "*":
                            continue
                        local = alias.asname or alias.name
                        candidates.setdefault(local, []).append(_ImportTarget(module, alias.name))
                case _:
                    pass

        imported_names = frozenset(candidates)
        non_import_bindings = _non_import_bindings(tree)
        rebound = non_import_bindings & imported_names
        bindings = {
            local: targets[0] for local, targets in candidates.items() if len(targets) == 1 and local not in rebound
        }
        return cls(MappingProxyType(bindings), frozenset(non_import_bindings))

    def resolves(self, node: ast.expr, *, sources: frozenset[str], symbol: str) -> bool:
        """Report whether `node` unambiguously names `symbol` from `sources`."""
        resolved = self._resolve(node)
        return resolved is not None and resolved.module in sources and resolved.symbol == symbol

    def builtin_is_unshadowed(self, name: str) -> bool:
        """Report whether a builtin spelling has no binding anywhere in this file."""
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
    """Collect possible import shadows, accepting false negatives over alias mistakes."""
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
