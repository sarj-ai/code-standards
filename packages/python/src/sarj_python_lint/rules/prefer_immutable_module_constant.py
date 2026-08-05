"""SARJ096 — Module constants should not expose mutable collection state.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_immutable_module_constant.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, Severity, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_generated, is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_CONSTANT_NAME = re.compile(r"^_?[A-Z][A-Z0-9_]*$")
_MUTATING_METHODS = frozenset(
    {
        "add",
        "append",
        "clear",
        "difference_update",
        "discard",
        "extend",
        "insert",
        "intersection_update",
        "pop",
        "popitem",
        "remove",
        "reverse",
        "setdefault",
        "sort",
        "symmetric_difference_update",
        "update",
    }
)


class PreferImmutableModuleConstant(Rule):
    id: str = "prefer-immutable-module-constant"
    code: str = "SARJ096"
    description: str = (
        "module-level constant collections expose mutable shared state; use tuple, frozenset, or an immutable mapping"
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_test_path(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        mutated = _mutated_names(tree)
        findings: list[Diagnostic] = []
        for statement in tree.body:
            binding = _binding(statement)
            if binding is None:
                continue
            name, value = binding
            kind = _mutable_literal_kind(value)
            if kind is None or name in mutated or not _CONSTANT_NAME.fullmatch(name) or name.startswith("__"):
                continue
            findings.append(
                Diagnostic(
                    path,
                    statement.lineno,
                    statement.col_offset + 1,
                    self.code,
                    _message(name, kind),
                    Severity.WARNING,
                )
            )
        return findings


def _binding(statement: ast.stmt) -> tuple[str, ast.expr] | None:
    match statement:
        case ast.Assign(targets=[ast.Name(id=name)], value=value):
            return name, value
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value):
            return name, value
        case _:
            return None


def _mutable_literal_kind(value: ast.expr) -> str | None:
    match value:
        case ast.List():
            return "list"
        case ast.Set():
            return "set"
        case ast.Dict():
            return "dict"
        case ast.Call(func=ast.Name(id=kind)) if kind in {"set", "dict", "list"}:
            return kind
        case _:
            return None


def _mutated_names(tree: ast.Module) -> frozenset[str]:
    mutated: set[str] = set()
    module_bindings: dict[str, int] = {}
    for statement in tree.body:
        binding = _binding(statement)
        if binding is not None:
            name, _ = binding
            module_bindings[name] = module_bindings.get(name, 0) + 1
    mutated.update(name for name, count in module_bindings.items() if count > 1)
    for node in nodes(tree, ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete, ast.Call):
        match node:
            case ast.Assign(targets=targets):
                mutated.update(name for target in targets if (name := _mutated_target(target)) is not None)
            case ast.AnnAssign(target=target):
                if name := _mutated_target(target):
                    mutated.add(name)
            case ast.AugAssign(target=ast.Name(id=name)):
                mutated.add(name)
            case ast.AugAssign(target=target):
                if name := _mutated_target(target):
                    mutated.add(name)
            case ast.Delete(targets=targets):
                mutated.update(name for target in targets if (name := _mutated_target(target)) is not None)
            case ast.Call(func=ast.Attribute(value=value, attr=method)) if method in _MUTATING_METHODS:
                if name := _root_name(value):
                    mutated.add(name)
            case _:
                continue
    return frozenset(mutated)


def _mutated_target(target: ast.expr) -> str | None:
    match target:
        case ast.Subscript(value=value) | ast.Attribute(value=value):
            return _root_name(value)
        case _:
            return None


def _root_name(value: ast.expr) -> str | None:
    match value:
        case ast.Name(id=name):
            return name
        case ast.Subscript(value=parent) | ast.Attribute(value=parent):
            return _root_name(parent)
        case _:
            return None


def _message(name: str, kind: str) -> str:
    replacement = {"list": "tuple", "set": "frozenset", "dict": "an immutable mapping"}[kind]
    return f"module constant `{name}` is a mutable {kind} — use {replacement} so shared state cannot drift at runtime."
