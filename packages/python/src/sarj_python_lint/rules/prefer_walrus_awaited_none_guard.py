from __future__ import annotations

import ast
from io import StringIO
from itertools import pairwise
from pathlib import PurePosixPath
import tokenize
from typing import TYPE_CHECKING, ClassVar, Literal, NamedTuple, final, override

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
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


_MAX_COMBINED_LINE_LENGTH = 120
type _NameFlow = Literal["ambiguous", "loaded", "none", "rebound", "terminal"]


class _WalrusCandidate(NamedTuple):
    name: str
    awaited: ast.Await
    is_not_none: bool


@final
class PreferWalrusAwaitedNoneGuard(Rule):
    id = "prefer-walrus-awaited-none-guard"
    code = "SARJ432"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Bind a compact awaited lookup in its immediately following terminal None guard.",
        rationale=(
            "When an awaited lookup and its terminal None guard are adjacent, binding in the condition keeps "
            "the operation, branch decision, and temporary name in one compact expression."
        ),
        remediation=(
            "Rewrite `value = await lookup(); if value is None: return` as "
            "`if (value := await lookup()) is None: return`. Preserve `is not None` when the terminal branch "
            "returns or raises with the bound value. Keep two statements when the assignment is an intentional "
            "debugging or tracing boundary."
        ),
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only one-line awaited calls followed immediately by an exact `is None` or `is not None` guard containing one return or raise are checked.",
            "A negative guard requires a later use on the surviving path; a positive guard must consume the binding in its terminal statement and leave no later use before rebinding.",
            "The combined condition must fit 120 columns; comments, else branches, ambiguous name flow, generated files, and broader assignment-expression preferences are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="awaited-optional-lookup",
                title="An awaited lookup is split from its absence guard",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "async def load(store, item_id):\n"
                        "    item = await store.get(item_id)\n"
                        "    if item is None:\n"
                        "        return\n"
                        "    return item.name\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="guard-bound-lookup",
                title="The awaited lookup is bound in its absence guard",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "async def load(store, item_id):\n"
                        "    if (item := await store.get(item_id)) is None:\n"
                        "        return\n"
                        "    return item.name\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if path.suffix == ".pyi" or is_generated(path, source):
            return []
        if any(token not in source for token in ("await", "None", "if", "=")):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        source_lines = source.splitlines()
        comment_lines = _comment_lines(source)
        diagnostics: list[Diagnostic] = []
        for body in _statement_lists(tree):
            for index, (assignment, guard) in enumerate(pairwise(body)):
                candidate = _candidate(assignment, guard, source, source_lines, comment_lines)
                if candidate is None:
                    continue
                name, awaited, is_not_none = candidate
                later_flow = _name_flow(body[index + 2 :], name)
                if (is_not_none and later_flow in {"ambiguous", "loaded"}) or (
                    not is_not_none and later_flow != "loaded"
                ):
                    continue
                if is_suppressed(source_lines, assignment.lineno, self.code) or is_suppressed(
                    source_lines, guard.lineno, self.code
                ):
                    continue
                expression = ast.get_source_segment(source, awaited)
                if expression is None:
                    continue
                diagnostics.append(
                    Diagnostic(
                        path=path,
                        line=assignment.lineno,
                        col=assignment.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=(
                            f"`{name}` only separates an awaited lookup from its terminal None guard; "
                            f"bind it as `if ({name} := {expression.strip()}) "
                            f"is {'not ' if is_not_none else ''}None:`"
                        ),
                    )
                )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _candidate(
    assignment: ast.stmt,
    guard: ast.stmt,
    source: str,
    source_lines: list[str],
    comment_lines: frozenset[int],
) -> _WalrusCandidate | None:
    if not (
        isinstance(assignment, ast.Assign)
        and len(assignment.targets) == 1
        and isinstance(assignment.targets[0], ast.Name)
        and isinstance(assignment.value, ast.Await)
        and isinstance(assignment.value.value, ast.Call)
        and assignment.end_lineno is not None
        and assignment.lineno == assignment.end_lineno
        and isinstance(guard, ast.If)
        and guard.lineno == assignment.end_lineno + 1
        and guard.col_offset == assignment.col_offset
        and guard.test.end_lineno == guard.lineno
        and not guard.orelse
        and len(guard.body) == 1
        and isinstance(guard.body[0], (ast.Return, ast.Raise))
    ):
        return None
    name = assignment.targets[0].id
    is_not_none = _none_guard_kind(guard.test, name)
    if is_not_none is None or _loads_name(assignment.value, name):
        return None
    terminal = guard.body[0]
    usage = _NameUsage(name)
    usage.visit(terminal)
    if usage.rebound or (is_not_none != usage.loaded):
        return None
    terminal_end = terminal.end_lineno or terminal.lineno
    if comment_lines.intersection(range(assignment.lineno, terminal_end + 1)):
        return None
    expression = ast.get_source_segment(source, assignment.value)
    if expression is None:
        return None
    original_line = source_lines[assignment.lineno - 1]
    indentation = original_line[: len(original_line) - len(original_line.lstrip())].expandtabs(8)
    combined = f"{indentation}if ({name} := {expression.strip()}) is {'not ' if is_not_none else ''}None:"
    if terminal.lineno == guard.lineno:
        terminal_source = ast.get_source_segment(source, terminal)
        if terminal_source is None:
            return None
        combined = f"{combined} {terminal_source.strip()}"
    if len(combined) > _MAX_COMBINED_LINE_LENGTH:
        return None
    return _WalrusCandidate(name, assignment.value, is_not_none)


def _none_guard_kind(test: ast.expr, name: str) -> bool | None:
    if not (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == name
        and len(test.ops) == 1
        and isinstance(test.ops[0], (ast.Is, ast.IsNot))
        and len(test.comparators) == 1
        and isinstance(test.comparators[0], ast.Constant)
        and test.comparators[0].value is None
    ):
        return None
    return isinstance(test.ops[0], ast.IsNot)


def _loads_name(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) and child.id == name for child in ast.walk(node)
    )


def _name_flow(statements: list[ast.stmt], name: str) -> _NameFlow:
    for statement in statements:
        usage = _NameUsage(name)
        usage.visit(statement)
        if usage.loaded and usage.rebound:
            return "ambiguous"
        if usage.rebound:
            return "rebound"
        if usage.loaded:
            return "loaded"
        if isinstance(statement, (ast.Break, ast.Continue, ast.Raise, ast.Return)):
            return "terminal"
    return "none"


@final
class _NameUsage(ast.NodeVisitor):
    def __init__(self, name: str) -> None:
        self.name = name
        self.loaded = False
        self.rebound = False

    def visit_Name(self, node: ast.Name) -> None:
        if node.id != self.name:
            return
        if isinstance(node.ctx, ast.Load):
            self.loaded = True
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.rebound = True

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.rebound |= node.name == self.name

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.rebound |= node.name == self.name

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.rebound |= node.name == self.name

    @override
    def visit_Lambda(self, node: ast.Lambda) -> None:
        _ = node

    @override
    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        _ = node

    def visit_Import(self, node: ast.Import) -> None:
        self.rebound |= any((alias.asname or alias.name.split(".", maxsplit=1)[0]) == self.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.rebound |= any((alias.asname or alias.name) == self.name for alias in node.names)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name == self.name:
            self.rebound = True
            return
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name == self.name:
            self.rebound = True
            return
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        self.rebound |= node.name == self.name

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest == self.name:
            self.rebound = True
            return
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.rebound |= self.name in node.names

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.rebound |= self.name in node.names


def _statement_lists(tree: ast.AST) -> list[list[ast.stmt]]:
    result: list[list[ast.stmt]] = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            value = getattr(node, field, None)
            if not isinstance(value, list):
                continue
            statements: list[ast.stmt] = []
            for item in value:  # pyright: ignore[reportUnknownVariableType] -- AST fields are untyped lists
                if not isinstance(item, ast.stmt):
                    break
                statements.append(item)
            else:
                if statements:
                    result.append(statements)
    return result


def _comment_lines(source: str) -> frozenset[int]:
    try:
        tokens = tokenize.generate_tokens(StringIO(source).readline)
        return frozenset(token.start[0] for token in tokens if token.type == tokenize.COMMENT)
    except IndentationError, tokenize.TokenError:
        return frozenset()
