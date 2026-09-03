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
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._comments import all_comments
from sarj_python_lint.rules._paths import is_generated


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
            "Arms with different bound names or comments, intervening or leading comments, and combined patterns rejected by Python are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="duplicate-match-arms",
                title="Adjacent match arms repeat one body",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/settings.py",
                        "def status(value):\n"
                        "    match value:\n"
                        "        case 'queued':\n"
                        "            return 'active'\n"
                        "        case 'running':\n"
                        "            return 'active'\n",
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
                        "def status(value):\n"
                        "    match value:\n"
                        "        case 'queued' | 'running':\n"
                        "            return 'active'\n",
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
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        match_nodes = [node for node in nodes(tree, ast.Match) if _has_structural_candidate(node)]
        if not match_nodes:
            return []
        if is_generated(path, source):
            return []
        comment_scan, _first_code_line = all_comments(source)
        comments = [(comment.line, comment.column, comment.body, comment.standalone) for comment in comment_scan]
        diags = [
            Diagnostic(
                path=path,
                line=run[0].pattern.lineno,
                col=run[0].pattern.col_offset + 1,
                code=self.code,
                message=_message(run),
                severity=Severity.WARNING,
            )
            for node in match_nodes
            for run in _mergeable_runs(node, comments)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _mergeable_runs(node: ast.Match, comments: list[tuple[int, int, str, bool]]) -> list[list[ast.match_case]]:
    runs: list[list[ast.match_case]] = []
    current: list[ast.match_case] = []
    for index, case in enumerate(node.cases):
        candidate_patterns = [*(arm.pattern for arm in current), case.pattern]
        if (
            current
            and _is_mergeable_arm(case)
            and not (len(current) == 1 and _has_leading_comment(node, index - 1, comments))
            and _arms_merge(current[-1], case, comments)
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


def _has_structural_candidate(node: ast.Match) -> bool:
    return any(
        _arms_structurally_merge(first, second)
        and _render_valid_or_pattern([first.pattern, second.pattern]) is not None
        for first, second in zip(node.cases, node.cases[1:], strict=False)
    )


def _is_mergeable_arm(case: ast.match_case) -> bool:
    if case.guard is not None:
        return False
    if _is_irrefutable(case.pattern):
        return False
    return not _is_empty_body(case.body)


def _is_irrefutable(pattern: ast.pattern) -> bool:
    if isinstance(pattern, ast.MatchAs):
        return pattern.pattern is None or _is_irrefutable(pattern.pattern)
    if isinstance(pattern, ast.MatchOr):
        return any(_is_irrefutable(member) for member in pattern.patterns)
    return False


def _is_empty_body(body: list[ast.stmt]) -> bool:
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, _EMPTY_BODY_NODES):
        return True
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)


def _arms_merge(
    first: ast.match_case,
    second: ast.match_case,
    comments: list[tuple[int, int, str, bool]],
) -> bool:
    if not _arms_structurally_merge(first, second):
        return False
    if _comments_in(comments, first.pattern.lineno, _arm_end(first)) != _comments_in(
        comments, second.pattern.lineno, _arm_end(second)
    ):
        return False
    # A comment in the gap groups the arms deliberately.
    return not _comments_in(comments, _arm_end(first) + 1, second.pattern.lineno - 1)


def _arms_structurally_merge(first: ast.match_case, second: ast.match_case) -> bool:
    return (
        _is_mergeable_arm(first)
        and _is_mergeable_arm(second)
        and _bound_names(first.pattern) == _bound_names(second.pattern)
        and _bodies_equal(first.body, second.body)
    )


def _has_leading_comment(
    node: ast.Match,
    case_index: int,
    comments: list[tuple[int, int, str, bool]],
) -> bool:
    start = node.lineno + 1 if case_index == 0 else _arm_end(node.cases[case_index - 1]) + 1
    return bool(_comments_in(comments, start, node.cases[case_index].pattern.lineno - 1))


def _arm_end(case: ast.match_case) -> int:
    return case.body[-1].end_lineno or case.body[-1].lineno


def _bodies_equal(first: list[ast.stmt], second: list[ast.stmt]) -> bool:
    if len(first) != len(second):
        return False
    return all(ast.dump(a) == ast.dump(b) for a, b in zip(first, second, strict=True))


def _bound_names(pattern: ast.pattern) -> frozenset[str]:
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


def _comments_in(comments: list[tuple[int, int, str, bool]], start: int, end: int) -> tuple[str, ...]:
    return tuple(body for line, _column, body, _standalone in comments if start <= line <= end)


def _message(run: list[ast.match_case]) -> str:
    preview = _preview([case.pattern for case in run])
    prefix = f"{len(run)} consecutive `case` arms repeat an identical body — merge them "
    if preview is None:
        return f"{prefix}into one or-pattern so the shared handling is written once."
    return f"{prefix}into one or-pattern (`case {preview}:`) so the shared handling is written once."


def _preview(patterns: list[ast.pattern]) -> str | None:
    preview = _render_valid_or_pattern(patterns)
    return preview if preview is not None and len(preview) <= _MAX_RENDERED_PREVIEW else None


def _render_valid_or_pattern(patterns: list[ast.pattern]) -> str | None:
    try:
        preview = ast.unparse(ast.MatchOr(patterns=patterns))
        compile(f"match subject:\n    case {preview}:\n        pass\n", "<sarj-or-pattern>", "exec")
    except SyntaxError, ValueError, AttributeError, TypeError, RecursionError:
        return None
    return preview
