"""SARJ096 — Module constants should not expose mutable collection state.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_immutable_module_constant.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, Severity, parse_or_none
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
        shadowed_builtins = _module_bound_names(tree) & {"dict", "list", "set"}
        findings: list[Diagnostic] = []
        for statement in tree.body:
            for name, value in _bindings(statement):
                kind = _mutable_literal_kind(value, shadowed_builtins=shadowed_builtins)
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


def _bindings(statement: ast.stmt) -> tuple[tuple[str, ast.expr], ...]:
    match statement:
        case ast.Assign(targets=targets, value=value):
            return tuple((target.id, value) for target in targets if isinstance(target, ast.Name))
        case ast.AnnAssign(target=ast.Name(id=name), value=ast.expr() as value):
            return ((name, value),)
        case _:
            return ()


def _mutable_literal_kind(value: ast.expr, *, shadowed_builtins: set[str]) -> str | None:
    match value:
        case ast.List():
            return "list"
        case ast.Set():
            return "set"
        case ast.Dict():
            return "dict"
        case ast.Call(func=ast.Name(id=kind)) if kind in {"set", "dict", "list"} and kind not in shadowed_builtins:
            return kind
        case _:
            return None


def _mutated_names(tree: ast.Module) -> frozenset[str]:
    mutated: set[str] = set()
    module_bindings: dict[str, int] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) > 1:
            # Skip every chained alias because mutation or escape through one name changes them all.
            mutated.update(target.id for target in statement.targets if isinstance(target, ast.Name))
        for name, _ in _bindings(statement):
            module_bindings[name] = module_bindings.get(name, 0) + 1
    mutated.update(name for name, count in module_bindings.items() if count > 1)
    visitor = _MutationVisitor(mutated)
    visitor.visit(tree)
    return frozenset(mutated)


class _MutationVisitor(ast.NodeVisitor):
    """Find mutations that resolve to module names, respecting lexical shadowing."""

    def __init__(self, mutated: set[str]) -> None:
        self.mutated: set[str] = mutated
        self._scopes: list[tuple[set[str], set[str]]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        locals_ = _argument_names(node.args)
        self._scopes.append((locals_, set()))
        self.visit(node.body)
        self._scopes.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        globals_ = _scope_global_names(node.body)
        locals_ = (_scope_bound_names(node.body) | _argument_names(node.args)) - globals_
        self._scopes.append((locals_, globals_))
        for statement in node.body:
            self.visit(statement)
        self._scopes.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scopes.append((_scope_bound_names(node.body), set()))
        for statement in node.body:
            self.visit(statement)
        self._scopes.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        self._record_targets(node.targets)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record_targets((node.target,))
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._record_name(
            _mutated_target(node.target) or (node.target.id if isinstance(node.target, ast.Name) else None)
        )
        self.visit(node.value)

    def visit_Delete(self, node: ast.Delete) -> None:
        self._record_targets(node.targets)

    def visit_Call(self, node: ast.Call) -> None:
        match node.func:
            case ast.Attribute(value=value, attr=method) if method in _MUTATING_METHODS:
                self._record_name(_root_name(value))
            case _:
                pass
        if not (
            isinstance(node.func, ast.Name) and node.func.id in {"all", "any", "frozenset", "iter", "len", "tuple"}
        ):
            for argument in (*node.args, *(keyword.value for keyword in node.keywords)):
                self._record_name(_root_name(argument))
        self.generic_visit(node)

    def _record_targets(self, targets: tuple[ast.expr, ...] | list[ast.expr]) -> None:
        for target in targets:
            self._record_name(_mutated_target(target))

    def _record_name(self, name: str | None) -> None:
        if name is None:
            return
        if not self._scopes:
            self.mutated.add(name)
            return
        for locals_, globals_ in reversed(self._scopes):
            if name in globals_:
                self.mutated.add(name)
                return
            if name in locals_:
                return
        self.mutated.add(name)


def _scope_global_names(body: list[ast.stmt]) -> set[str]:
    return {name for statement in body if isinstance(statement, ast.Global) for name in statement.names}


def _scope_bound_names(body: list[ast.stmt]) -> set[str]:
    names: set[str] = set()
    for statement in body:
        match statement:
            case ast.Assign(targets=targets):
                names.update(target.id for target in targets if isinstance(target, ast.Name))
            case ast.AnnAssign(target=ast.Name(id=name)) | ast.AugAssign(target=ast.Name(id=name)):
                names.add(name)
            case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
                names.update(alias.asname or alias.name.split(".", maxsplit=1)[0] for alias in aliases)
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.ClassDef(name=name):
                names.add(name)
            case _:
                pass
    return names


def _argument_names(arguments: ast.arguments) -> set[str]:
    names = {argument.arg for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)
    return names


def _module_bound_names(tree: ast.Module) -> set[str]:
    return _scope_bound_names(tree.body)


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
