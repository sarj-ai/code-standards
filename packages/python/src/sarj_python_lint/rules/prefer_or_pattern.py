"""SARJ070 — Adjacent `case` arms with identical bodies — merge them into one or-pattern.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_prefer_or_pattern.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
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
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk


if TYPE_CHECKING:
    from pathlib import Path


# A run must contain at least this many arms before merging buys anything.
_MIN_RUN = 2

# Preview complete suggested syntax only when it fits comfortably in one line.
_MAX_RENDERED_PREVIEW = 96

# Statement shapes that make an arm body empty.
_EMPTY_BODY_NODES = (ast.Pass,)


class PreferOrPattern(Rule):
    id: str = "prefer-or-pattern"
    code: str = "SARJ070"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Merge adjacent `case` arms with identical bodies into one or-pattern.",
        rationale="An or-pattern expresses shared handling once and prevents identical arms from drifting apart.",
        remediation="Join the equivalent patterns with `|` and keep their shared body under the merged arm.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only adjacent, unguarded, refutable arms with structurally identical non-empty bodies are compared.",
            "Arms with different bound names, comments, or a combined pattern rejected by Python are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="duplicate-match-arms",
                title="Adjacent match arms repeat one body",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "def configure(value):\n"
                        "    match value:\n"
                        "        case LocalSettings():\n"
                        "            return build(value)\n"
                        "        case RemoteSettings():\n"
                        "            return build(value)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="shared-or-pattern-arm",
                title="One or-pattern owns the shared body",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "def configure(value):\n"
                        "    match value:\n"
                        "        case LocalSettings() | RemoteSettings():\n"
                        "            return build(value)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/settings.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag runs of adjacent `case` arms that duplicate one body."""
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        lines = source.splitlines()
        diags = [
            Diagnostic(
                path=path,
                line=run[0].pattern.lineno,
                col=run[0].pattern.col_offset + 1,
                code=self.code,
                message=_message(run),
            )
            for node in nodes(tree, ast.Match)
            for run in _mergeable_runs(node, lines)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _mergeable_runs(node: ast.Match, lines: list[str]) -> list[list[ast.match_case]]:
    """Group the match's arms into maximal runs of adjacent, mergeable arms."""
    runs: list[list[ast.match_case]] = []
    current: list[ast.match_case] = []
    for case in node.cases:
        candidate_patterns = [*(arm.pattern for arm in current), case.pattern]
        if (
            current
            and _is_mergeable_arm(case)
            and _arms_merge(current[-1], case, lines)
            and _render_valid_or_pattern(candidate_patterns) is not None
        ):
            current.append(case)
            continue
        if len(current) >= _MIN_RUN:
            runs.append(current)
        current = [case] if _is_mergeable_arm(case) else []
    if len(current) >= _MIN_RUN:
        runs.append(current)
    return runs


def _is_mergeable_arm(case: ast.match_case) -> bool:
    """Report whether an arm can ever take part in an or-pattern merge."""
    if case.guard is not None:
        return False
    if _is_irrefutable(case.pattern):
        return False
    return not _is_empty_body(case.body)


def _is_irrefutable(pattern: ast.pattern) -> bool:
    """Report whether `pattern` matches everything (`case _:` or `case name:`)."""
    return isinstance(pattern, ast.MatchAs) and pattern.pattern is None


def _is_empty_body(body: list[ast.stmt]) -> bool:
    """Report whether the arm body does nothing at all."""
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, _EMPTY_BODY_NODES):
        return True
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis


def _arms_merge(first: ast.match_case, second: ast.match_case, lines: list[str]) -> bool:
    """Report whether two adjacent arms can be folded into one or-pattern."""
    if _bound_names(first.pattern) != _bound_names(second.pattern):
        return False
    if not _bodies_equal(first.body, second.body):
        return False
    if _comments_in(lines, first.pattern.lineno, _arm_end(first)) != _comments_in(
        lines, second.pattern.lineno, _arm_end(second)
    ):
        return False
    # A comment in the gap groups the arms deliberately.
    return not _comments_in(lines, _arm_end(first) + 1, second.pattern.lineno - 1)


def _arm_end(case: ast.match_case) -> int:
    """Return the last source line the arm occupies."""
    return case.body[-1].end_lineno or case.body[-1].lineno


def _bodies_equal(first: list[ast.stmt], second: list[ast.stmt]) -> bool:
    """Compare two statement blocks structurally, ignoring source positions."""
    if len(first) != len(second):
        return False
    return all(ast.dump(a) == ast.dump(b) for a, b in zip(first, second, strict=True))


def _bound_names(pattern: ast.pattern) -> frozenset[str]:
    """Collect every name the pattern binds."""
    names: set[str] = set()
    for node in walk(pattern):
        match node:
            case ast.MatchAs(name=str() as name) | ast.MatchStar(name=str() as name):
                names.add(name)
            case ast.MatchMapping(rest=str() as rest):
                names.add(rest)
            case _:
                pass
    return frozenset(names)


def _comments_in(lines: list[str], start: int, end: int) -> tuple[str, ...]:
    """Collect the `#` tails on the 1-based inclusive line range `start..end`."""
    found: list[str] = []
    for index in range(max(start, 1), min(end, len(lines)) + 1):
        _, sep, tail = lines[index - 1].partition("#")
        if sep:
            found.append(tail.strip())
    return tuple(found)


def _message(run: list[ast.match_case]) -> str:
    """Describe the merge, including complete syntax only when it fits."""
    preview = _preview(run[0].pattern, run[1].pattern)
    prefix = f"{len(run)} consecutive `case` arms repeat an identical body — merge them "
    if preview is None:
        return f"{prefix}into one or-pattern so the shared handling is written once."
    return f"{prefix}into one or-pattern (`case {preview}:`) so the shared handling is written once."


def _preview(first: ast.pattern, second: ast.pattern) -> str | None:
    """Render a complete parseable two-pattern suggestion, if it fits."""
    preview = _render_valid_or_pattern([first, second])
    return preview if preview is not None and len(preview) <= _MAX_RENDERED_PREVIEW else None


def _render_valid_or_pattern(patterns: list[ast.pattern]) -> str | None:
    """Render an or-pattern only when Python accepts its capture layout."""
    try:
        preview = ast.unparse(ast.MatchOr(patterns=patterns))
        compile(f"match subject:\n    case {preview}:\n        pass\n", "<sarj-or-pattern>", "exec")
    except SyntaxError, ValueError, AttributeError, TypeError, RecursionError:
        return None
    return preview
