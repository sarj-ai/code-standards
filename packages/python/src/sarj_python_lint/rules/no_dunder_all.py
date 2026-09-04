from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


class _Location(NamedTuple):
    line: int
    column: int


@final
class NoDunderAll(Rule):
    id = "no-dunder-all"
    code = "SARJ438"
    documentation = RuleDocumentation(
        summary="modules should not define or mutate `__all__`",
        rationale=(
            "`__all__` creates a second, mutable wildcard-import surface that can drift from runtime bindings; "
            "Sarj code uses explicit imports and private-name conventions instead."
        ),
        remediation=(
            "Before deleting `__all__`, replace wildcard-import consumers with explicit imports, retain each intended "
            "binding, and prefix implementation-only bindings with `_`. Use self-aliased imports to mark intentional "
            "re-exports to static tooling."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Reads, attributes on other objects, indirect mutation through arbitrary calls, and ordinary local "
                "variables are not reported; the rule targets module-owned bindings and provable mutations."
            ),
            "Writes inside a function or class are reported only when that lexical scope declares `global __all__`.",
            "Generated source, malformed source, and stub files (`.pyi`) are outside this rule's scope.",
            "Dynamic construction through `globals()`, `setattr()`, or `exec()` is not inferred.",
            (
                "No autofix is offered because removal can change `module.__all__` introspection, wildcard imports, "
                "underscore-name exports, ordering, and dynamic or conditional export behavior."
            ),
        ),
        examples=(
            RuleExample(
                example_id="duplicated-export-list",
                title="Do not repeat an explicit re-export list",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "diagnostics/__init__.py",
                        'from .models import Diagnostic as Diagnostic\n\n__all__ = ["Diagnostic"]\n',
                    ),
                ),
                focus_path=PurePosixPath("diagnostics/__init__.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-re-export",
                title="Make the re-export explicit in the import",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "diagnostics/__init__.py",
                        "from .models import Diagnostic as Diagnostic\n",
                    ),
                ),
                focus_path=PurePosixPath("diagnostics/__init__.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix != ".py" or "__all__" not in source or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        findings: list[Diagnostic] = []
        for statement in _module_statements(tree.body):
            if (location := _dunder_all_location(statement)) is None:
                continue
            findings.append(
                Diagnostic(
                    path=path,
                    line=location.line,
                    col=location.column,
                    code=self.code,
                    message="Remove the module-owned `__all__` binding or mutation; use explicit imports instead.",
                )
            )
        return sorted(findings, key=lambda finding: (finding.line, finding.col, finding.code))


def _module_statements(statements: list[ast.stmt]) -> list[ast.stmt]:
    result: list[ast.stmt] = []
    pending = list(reversed(statements))
    while pending:
        statement = pending.pop()
        result.append(statement)
        nested = _module_control_flow_bodies(statement)
        pending.extend(reversed(nested))
    return result


def _module_control_flow_bodies(statement: ast.stmt) -> list[ast.stmt]:
    match statement:
        case ast.If() | ast.For() | ast.AsyncFor() | ast.While():
            return [*statement.body, *statement.orelse]
        case ast.With() | ast.AsyncWith():
            return list(statement.body)
        case ast.Try() | ast.TryStar():
            return [
                *statement.body,
                *(nested for handler in statement.handlers for nested in handler.body),
                *statement.orelse,
                *statement.finalbody,
            ]
        case ast.Match():
            return [nested for match_case in statement.cases for nested in match_case.body]
        case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef() if _declares_global_dunder_all(statement.body):
            return list(statement.body)
        case _:
            return []


def _dunder_all_location(statement: ast.stmt) -> _Location | None:
    visitor = _DunderAllVisitor()
    visitor.visit(statement)
    return min(visitor.locations, default=None)


_MUTATING_METHODS = frozenset({"append", "clear", "extend", "insert", "pop", "remove", "reverse", "sort"})


class _ScopePruningVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.locations: list[_Location] = []

    def _record(self, node: ast.expr | ast.stmt | ast.alias | ast.ExceptHandler | ast.pattern) -> None:
        self.locations.append(_Location(node.lineno, node.col_offset + 1))

    @override
    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "__all__" and isinstance(node.ctx, (ast.Store, ast.Del)):
            self._record(node)

    @override
    def visit_alias(self, node: ast.alias) -> None:
        bound_name = node.asname or node.name.split(".", maxsplit=1)[0]
        if bound_name == "__all__":
            self._record(node)

    @override
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == "__all__":
            self._record(node)
        self._visit_definition_header(node)

    @override
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node.name == "__all__":
            self._record(node)
        self._visit_definition_header(node)

    def _visit_definition_header(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in (*node.args.defaults, *(value for value in node.args.kw_defaults if value is not None)):
            self.visit(default)
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if argument.annotation is not None:
                self.visit(argument.annotation)
        if node.args.vararg is not None and node.args.vararg.annotation is not None:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
            self.visit(node.args.kwarg.annotation)
        if node.returns is not None:
            self.visit(node.returns)
        for type_param in node.type_params:
            self.visit(type_param)

    @override
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name == "__all__":
            self._record(node)
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        for type_param in node.type_params:
            self.visit(type_param)

    @override
    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node

    @override
    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)

    @override
    def visit_For(self, node: ast.For) -> None:
        self.visit(node.target)
        self.visit(node.iter)

    @override
    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit(node.target)
        self.visit(node.iter)

    @override
    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)

    @override
    def visit_With(self, node: ast.With) -> None:
        self._visit_with_items(node.items)

    def _visit_with_items(self, items: list[ast.withitem]) -> None:
        for item in items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.visit(item.optional_vars)

    @override
    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_with_items(node.items)

    @override
    def visit_Try(self, node: ast.Try) -> None:
        self._visit_handlers(node.handlers)

    @override
    def visit_TryStar(self, node: ast.TryStar) -> None:
        self._visit_handlers(node.handlers)

    def _visit_handlers(self, handlers: list[ast.ExceptHandler]) -> None:
        for handler in handlers:
            if handler.type is not None:
                self.visit(handler.type)
            if handler.name == "__all__":
                self._record(handler)


class _DunderAllVisitor(_ScopePruningVisitor):
    @override
    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        for match_case in node.cases:
            self.visit(match_case.pattern)
            if match_case.guard is not None:
                self.visit(match_case.guard)

    @override
    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.pattern is not None:
            self.visit(node.pattern)
        if node.name == "__all__":
            self._record(node)

    @override
    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name == "__all__":
            self._record(node)

    @override
    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        for key in node.keys:
            self.visit(key)
        for pattern in node.patterns:
            self.visit(pattern)
        if node.rest == "__all__":
            self._record(node)

    @override
    def visit_Subscript(self, node: ast.Subscript) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)) and _is_dunder_all_root(node.value):
            self._record(node.value)
        self.generic_visit(node)

    @override
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)) and _is_dunder_all_root(node.value):
            self._record(node.value)
        self.generic_visit(node)

    @override
    def visit_Call(self, node: ast.Call) -> None:
        match node.func:
            case ast.Attribute(value=ast.Name(id="__all__") as owner, attr=method) if method in _MUTATING_METHODS:
                self._record(owner)
            case _:
                pass
        self.generic_visit(node)

    def _visit_comprehension(self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp) -> None:
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        for generator in node.generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)

    @override
    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node)

    @override
    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node)

    @override
    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node)

    @override
    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node)


def _is_dunder_all_root(node: ast.expr) -> bool:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return isinstance(node, ast.Name) and node.id == "__all__"


def _declares_global_dunder_all(statements: list[ast.stmt]) -> bool:
    pending: list[ast.AST] = list(statements)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Global) and "__all__" in node.names:
            return True
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        pending.extend(ast.iter_child_nodes(node))
    return False
