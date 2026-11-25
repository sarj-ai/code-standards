from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
)
from sarj_python_lint.rules._ast_index import object_list
from sarj_python_lint.rules._comments import comment_line_numbers


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_MAX_COMBINED_LINE_LENGTH = 120
_DEFERRED_EFFECTS = (ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr)
_EAGER_EXCLUSIONS = (ast.Yield, ast.YieldFrom, ast.NamedExpr)
_NEEDS_PARENTHESES = (ast.Tuple, ast.IfExp, ast.Lambda)


@final
class PreferNextOverSearchLoop(Rule):
    id = "prefer-next-over-search-loop"
    code = "SARJ590"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Replace a first-match search loop with next() over a generator expression.",
        rationale=(
            "A loop whose only job is to return the first matching item, followed by a fallback return, spreads "
            "one lookup over four statements. `next()` over a filtered generator states the search, the match "
            "condition and the fallback in one expression with the same laziness and short-circuiting."
        ),
        remediation=(
            "Rewrite `for item in items: if matches(item): return value(item)` followed by `return default` as "
            "`return next((value(item) for item in items if matches(item)), default)`. Keep the loop when the "
            "body grows side effects, logging or several exits."
        ),
        category=RuleCategory.STYLE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only a synchronous `for` loop without `else`, whose body is exactly one `if` without `else` whose body is exactly one `return <expression>`, immediately followed by `return`, `return None`, or `return` of a constant or a name not bound by the loop target, is checked.",
            "Loop targets must be names or nested tuples of names. Await in the outermost iterable is allowed because it is evaluated eagerly; await in the condition or result, and yield or assignment expressions anywhere, are excluded because a generator expression would change their scope or semantics.",
            "Constant match results are membership tests: boolean pairs belong to Ruff SIM110/SIM111 and other constants read better as `any()`. Comments in the span, multi-line pieces, suggestions over 120 columns, generated files and stub files are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="first-match-loop",
                title="A loop returns the first matching item with a fallback",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def find_admin(users):\n"
                        "    for user in users:\n"
                        "        if user.is_admin:\n"
                        "            return user\n"
                        "    return None\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="next-over-generator",
                title="next() states the search and its fallback together",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def find_admin(users):\n    return next((user for user in users if user.is_admin), None)\n",
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
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        source = context.source
        if path.suffix == ".pyi" or context.generated or context.tree is None:
            return []
        if any(token not in source for token in ("for", "return")):
            return []
        comment_lines = comment_line_numbers(source)
        diagnostics: list[Diagnostic] = []
        for loop in context.nodes(ast.For):
            fallback = _following_statement(loop, context.parents.get(loop))
            suggestion = _suggestion(loop, fallback, source)
            if suggestion is None or fallback is None:
                continue
            indentation = context.source_lines[loop.lineno - 1][: loop.col_offset].expandtabs(8)
            end_line = fallback.end_lineno or fallback.lineno
            if (
                len(indentation) + len(suggestion) > _MAX_COMBINED_LINE_LENGTH
                or comment_lines.intersection(range(loop.lineno, end_line + 1))
                or context.suppressions.is_suppressed(loop.lineno, self.code)
                or context.suppressions.is_suppressed(fallback.lineno, self.code)
            ):
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=loop.lineno,
                    col=loop.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=f"First-match search loop can be one expression: `{suggestion}`",
                )
            )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _following_statement(loop: ast.For, parent: ast.AST | None) -> ast.Return | None:
    if parent is None:
        return None
    for name in parent._fields:
        siblings: object = (
            getattr(  # sarj-noqa: SARJ557 -- Inspect statement-list fields across heterogeneous AST node types.
                parent, name, None
            )
        )
        if not object_list(siblings):
            continue
        for index, item in enumerate(siblings):
            if item is loop:
                following = siblings[index + 1] if index + 1 < len(siblings) else None
                return following if isinstance(following, ast.Return) else None
    return None


def _suggestion(loop: ast.For, fallback: ast.Return | None, source: str) -> str | None:
    match loop:
        case ast.For(body=[ast.If(test=condition, body=[ast.Return(value=ast.expr() as found)], orelse=[])], orelse=[]):
            pass
        case _:
            return None
    if fallback is None or not _simple_target(loop.target) or not _single_line(loop, fallback):
        return None
    if isinstance(found, ast.Constant) or _has_deferred_effect(loop, condition, found):
        return None
    if (default_source := _default_source(fallback.value, loop.target, source)) is None:
        return None
    pieces = [ast.get_source_segment(source, node) for node in (found, loop.target, loop.iter, condition)]
    if any(piece is None or "\n" in piece for piece in pieces):
        return None
    found_source, target_source, iterable_source, condition_source = (
        f"({piece})" if isinstance(node, _NEEDS_PARENTHESES) else piece
        for node, piece in zip((found, loop.target, loop.iter, condition), pieces, strict=True)
    )
    return (
        f"return next(({found_source} for {target_source} in {iterable_source} if {condition_source}), "
        f"{default_source})"
    )


def _has_deferred_effect(loop: ast.For, condition: ast.expr, found: ast.expr) -> bool:
    deferred = (loop.target, condition, found)
    return any(isinstance(node, _DEFERRED_EFFECTS) for part in deferred for node in ast.walk(part)) or any(
        isinstance(node, _EAGER_EXCLUSIONS) for node in ast.walk(loop.iter)
    )


def _default_source(default: ast.expr | None, target: ast.expr, source: str) -> str | None:
    match default:
        case ast.Name(id=name) if name in _target_names(target):
            return None
        case ast.Constant() | ast.Name():
            return ast.get_source_segment(source, default)
        case None:
            return "None"
        case _:
            return None


def _single_line(loop: ast.For, fallback: ast.Return) -> bool:
    match loop.body:
        case [ast.If(body=[found]) as guard]:
            pass
        case _:
            return False
    return (
        all(node.lineno == node.end_lineno for node in (guard.test, found, fallback))
        and loop.iter.end_lineno == loop.lineno
        and guard.test.lineno == guard.lineno
    )


def _simple_target(target: ast.expr) -> bool:
    match target:
        case ast.Name():
            return True
        case ast.Tuple(elts=elements):
            return bool(elements) and all(_simple_target(element) for element in elements)
        case _:
            return False


def _target_names(target: ast.expr) -> frozenset[str]:
    return frozenset(node.id for node in ast.walk(target) if isinstance(node, ast.Name))
