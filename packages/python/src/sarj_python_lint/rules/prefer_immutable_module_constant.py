from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
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
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary=(
            "module-level constant collections expose mutable shared state; use tuple, frozenset, or an immutable mapping"
        ),
        rationale=(
            "A constant-looking mutable collection can be changed by any importer, so its value depends on process history "
            "rather than the module's source."
        ),
        remediation=(
            "Use a tuple for ordered values, a frozenset for membership, or an immutable mapping for keyed values."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Empty collections and collections intentionally mutated or passed to unknown calls are not reported.",
            "Test and generated files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="mutable-module-constant",
                title="Mutable collection exposed as a module constant",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("settings.py", 'ROLE_NAMES = ["admin", "member"]\n'),),
                focus_path=PurePosixPath("settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="immutable-module-constant",
                title="Immutable tuple used for a module constant",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("settings.py", 'ROLE_NAMES = ("admin", "member")\n'),),
                focus_path=PurePosixPath("settings.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="mutable-module-mapping",
                scenario="keyed-values",
                title="Dictionary exposed as a module constant",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("settings.py", 'ROLE_LABELS = {"admin": "Administrator"}\n'),),
                focus_path=PurePosixPath("settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="immutable-module-mapping",
                scenario="keyed-values",
                title="Read-only mapping used for keyed values",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "settings.py",
                        'from types import MappingProxyType\n\nROLE_LABELS = MappingProxyType({"admin": "Administrator"})\n',
                    ),
                ),
                focus_path=PurePosixPath("settings.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

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
        case ast.List(elts=[]):
            return None
        case ast.ListComp() | ast.List():
            return "list"
        case ast.SetComp() | ast.Set():
            return "set"
        case ast.Dict(keys=[]):
            return None
        case ast.DictComp() | ast.Dict():
            return "dict"
        case ast.Call(func=ast.Name(id=kind), args=[], keywords=[]) if (
            kind in {"set", "dict", "list"} and kind not in shadowed_builtins
        ):
            return None
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
    def __init__(self, mutated: set[str]) -> None:
        self.mutated: set[str] = mutated
        self._scopes: list[tuple[set[str], set[str]]] = []
        self._local_container_roots: list[dict[str, set[str]]] = []
        self._module_container_roots: dict[str, set[str]] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in (*node.args.defaults, *(item for item in node.args.kw_defaults if item is not None)):
            self.visit(default)
        locals_ = _argument_names(node.args)
        self._scopes.append((locals_, set()))
        self._local_container_roots.append({})
        self.visit(node.body)
        self._local_container_roots.pop()
        self._scopes.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *(item for item in node.args.kw_defaults if item is not None)):
            self.visit(default)
        globals_ = _scope_global_names(node.body)
        locals_ = (_scope_bound_names(node.body) | _argument_names(node.args)) - globals_
        self._scopes.append((locals_, globals_))
        self._local_container_roots.append({})
        for statement in node.body:
            self.visit(statement)
        self._local_container_roots.pop()
        self._scopes.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expression in (*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords)):
            self.visit(expression)
        self._scopes.append((_scope_bound_names(node.body), set()))
        self._local_container_roots.append({})
        for statement in node.body:
            self.visit(statement)
        self._local_container_roots.pop()
        self._scopes.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        self._record_targets(node.targets)
        self._remember_local_container_roots(node.targets, node.value)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record_targets((node.target,))
        if node.value is not None:
            self._remember_local_container_roots((node.target,), node.value)
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
                for name in self._module_roots(argument, call_argument=True):
                    self._record_name(name)
        self.generic_visit(node)

    def _remember_local_container_roots(self, targets: tuple[ast.expr, ...] | list[ast.expr], value: ast.expr) -> None:
        roots = self._module_roots(value)
        if not roots:
            return
        if not self._local_container_roots:
            for target in targets:
                if isinstance(target, ast.Name):
                    self._module_container_roots.setdefault(target.id, set()).update(roots)
            return
        locals_ = self._scopes[-1][0]
        aliases = self._local_container_roots[-1]
        for target in targets:
            if isinstance(target, ast.Name) and target.id in locals_:
                aliases.setdefault(target.id, set()).update(roots)

    def _module_roots(self, value: ast.expr, *, call_argument: bool = False) -> set[str]:
        roots: set[str] = set()
        direct_root = _root_name(value) if call_argument else None
        names = (direct_root,) if direct_root is not None else _literal_container_root_names(value)
        for name in names:
            alias = next(
                (scope[name] for scope in reversed(self._local_container_roots) if name in scope),
                None,
            )
            if alias is None:
                alias = self._module_container_roots.get(name)
            if alias is not None:
                roots.update(alias)
            if self._is_module_reference(name):
                roots.add(name)
        return roots

    def _is_module_reference(self, name: str) -> bool:
        for locals_, globals_ in reversed(self._scopes):
            if name in globals_:
                return True
            if name in locals_:
                return False
        return True

    def _record_targets(self, targets: tuple[ast.expr, ...] | list[ast.expr]) -> None:
        for target in targets:
            name = _mutated_target(target)
            if name is None and isinstance(target, ast.Name) and self._scopes:
                name = target.id
            self._record_name(name)

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


class _BoundNameCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def _record_target(self, target: ast.expr) -> None:
        match target:
            case ast.Name(id=name):
                self.names.add(name)
            case ast.Tuple() | ast.List():
                for element in target.elts:
                    self._record_target(element)
            case ast.Starred(value=value):
                self._record_target(value)
            case _:
                pass

    @override
    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._record_target(target)
        self.visit(node.value)

    @override
    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record_target(node.target)
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)

    @override
    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._record_target(node.target)
        self.visit(node.value)

    @override
    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._record_target(node.target)
        self.visit(node.value)

    @override
    def visit_For(self, node: ast.For) -> None:
        self._visit_for(node)

    @override
    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_for(node)

    def _visit_for(self, node: ast.For | ast.AsyncFor) -> None:
        self._record_target(node.target)
        self.visit(node.iter)
        for statement in (*node.body, *node.orelse):
            self.visit(statement)

    @override
    def visit_With(self, node: ast.With) -> None:
        self._visit_with(node)

    @override
    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_with(node)

    def _visit_with(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._record_target(item.optional_vars)
        for statement in node.body:
            self.visit(statement)

    @override
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.names.add(node.name)
        if node.type is not None:
            self.visit(node.type)
        for statement in node.body:
            self.visit(statement)

    @override
    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.split(".", maxsplit=1)[0] for alias in node.names)

    @override
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names)

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    @override
    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    @override
    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self.names.add(node.name)
        if node.pattern is not None:
            self.visit(node.pattern)

    @override
    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self.names.add(node.name)

    @override
    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self.names.add(node.rest)
        self.generic_visit(node)


def _scope_bound_names(body: list[ast.stmt]) -> set[str]:
    collector = _BoundNameCollector()
    for statement in body:
        collector.visit(statement)
    return collector.names


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
        case ast.Subscript() | ast.Attribute():
            return _root_name(target.value)
        case _:
            return None


def _root_name(value: ast.expr) -> str | None:
    match value:
        case ast.Name(id=name):
            return name
        case ast.Subscript() | ast.Attribute():
            return _root_name(value.value)
        case _:
            return None


def _literal_container_root_names(value: ast.expr) -> tuple[str, ...]:
    match value:
        case ast.Name(id=name):
            return (name,)
        case ast.Attribute(value=parent, attr=method) if method in _MUTATING_METHODS:
            root = _root_name(parent)
            return (root,) if root is not None else ()
        case ast.Dict(keys=keys, values=values):
            items = (*[key for key in keys if key is not None], *values)
        case ast.List(elts=items) | ast.Tuple(elts=items) | ast.Set(elts=items):
            pass
        case ast.Starred(value=(ast.List() | ast.Tuple()) as item):
            items = (item,)
        case _:
            return ()
    return tuple(name for item in items for name in _literal_container_root_names(item))


def _message(name: str, kind: str) -> str:
    replacement = {"list": "tuple", "set": "frozenset", "dict": "an immutable mapping"}[kind]
    return f"module constant `{name}` is a mutable {kind} — use {replacement} so shared state cannot drift at runtime."
