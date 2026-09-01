from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
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
    parse_or_none,
)
from sarj_python_lint.rules._prose_budget import (
    groups,
    has_technical_anchor,
)


if TYPE_CHECKING:
    from pathlib import Path


_MIN_LINES = 4
_MIN_WORDS = 28
_RATIONALE_RE = re.compile(
    r"\b(?:because|otherwise|therefore|must|never|cannot|can't|required?|invariant|"
    r"compatibility|security|race|atomic|deadlock|rollback|lock|data loss)\b",
    re.IGNORECASE,
)
_RATIONALE_SO_RE = re.compile(r"\bso\s+(?:that|a|an|the|this|it|we|they)\b", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*+] |\d+[.)] )", re.MULTILINE)
_ACCUMULATOR_METHODS = frozenset({"add", "append", "extend", "update"})
_MIN_ACCUMULATOR_CALLS = 2


@final
class ExcessiveCommentary(Rule):
    id = "excessive-commentary"
    code = "SARJ434"
    documentation = RuleDocumentation(
        summary="Long standalone implementation commentary — make the code self-documenting and retain only durable constraints.",
        rationale=(
            "A paragraph that narrates nearby implementation behavior competes with the code and can drift independently "
            "from it."
        ),
        remediation=(
            "Delete the narration and clarify names, types, or structure. Keep concise comments that record a durable "
            "constraint or externally owned contract."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only contiguous standalone line-comment blocks with at least four non-empty lines and 28 words are inspected.",
            "The paragraph must immediately precede an empty local collection that is then populated by at least two consecutive accumulator calls.",
            "Generated files, directives, licenses, structured lists, docstrings, inline comments, rationale markers, and concrete technical anchors are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="activation-narration",
                title="Implementation paragraph narrates a validation helper",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        "def activation_reasons():\n"
                        "    # Everything standing between this integration and being usable.\n"
                        "    # Returns all the reasons rather than the first failure.\n"
                        "    # Someone activating a half-built integration wants the complete list.\n"
                        "    # That avoids discovering one problem per round trip.\n"
                        "    reasons = []\n"
                        "    reasons.extend(integration_reasons())\n"
                        "    reasons.extend(endpoint_reasons())\n"
                        "    return reasons\n",
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="durable-constraint",
                title="A concrete compatibility constraint remains local",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app.py",
                        "# Legacy clients send `execution_phase` until API-812 is retired.\n"
                        "# Keep the adapter at this boundary so internal models stay camelCase.\n"
                        'phase = payload["execution_phase"]\n',
                    ),
                ),
                focus_path=PurePosixPath("app.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        accumulator_lines = _narrated_accumulator_lines(tree)
        findings: list[Diagnostic] = []
        for group in groups(path, source):
            lines = tuple(stripped for line in group.text.splitlines() if (stripped := line.strip()))
            if group.kind != "comment" or len(lines) < _MIN_LINES or len(group.text.split()) < _MIN_WORDS:
                continue
            comment_end_line = group.line + len(group.text.splitlines()) - 1
            if comment_end_line + 1 not in accumulator_lines:
                continue
            if any(
                (
                    _BULLET_RE.search(group.text),
                    has_technical_anchor(group.text),
                    _RATIONALE_RE.search(group.text),
                    _RATIONALE_SO_RE.search(group.text),
                )
            ):
                continue
            findings.append(
                Diagnostic(
                    path,
                    group.line,
                    group.col,
                    self.code,
                    self.description,
                    column_encoding=group.column_encoding,
                )
            )
        return findings


def _narrated_accumulator_lines(tree: ast.Module) -> set[int]:
    lines: set[int] = set()
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        _collect_accumulators(function.body, lines)
    return lines


def _collect_accumulators(statements: list[ast.stmt], lines: set[int]) -> None:
    for index, statement in enumerate(statements):
        name = _empty_collection_name(statement)
        if name is not None:
            mutations = 0
            for following in statements[index + 1 :]:
                if not _is_accumulator_call(following, name):
                    break
                mutations += 1
            if mutations >= _MIN_ACCUMULATOR_CALLS:
                lines.add(statement.lineno)
        for child_statements in _nested_statement_lists(statement):
            _collect_accumulators(child_statements, lines)


def _empty_collection_name(statement: ast.stmt) -> str | None:
    target: ast.expr | None = None
    value: ast.expr | None = None
    if isinstance(statement, ast.AnnAssign):
        target, value = statement.target, statement.value
    elif isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target, value = statement.targets[0], statement.value
    if not isinstance(target, ast.Name) or value is None:
        return None
    if isinstance(value, (ast.List, ast.Set)) and not value.elts:
        return target.id
    if isinstance(value, ast.Dict) and not value.keys:
        return target.id
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in {"dict", "list", "set"}
        and not value.args
        and not value.keywords
    ):
        return target.id
    return None


def _is_accumulator_call(statement: ast.stmt, name: str) -> bool:
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return False
    function = statement.value.func
    return (
        isinstance(function, ast.Attribute)
        and function.attr in _ACCUMULATOR_METHODS
        and isinstance(function.value, ast.Name)
        and function.value.id == name
    )


def _nested_statement_lists(statement: ast.stmt) -> list[list[ast.stmt]]:
    match statement:
        case ast.For() | ast.AsyncFor() | ast.While() | ast.If():
            return [statement.body, statement.orelse]
        case ast.With() | ast.AsyncWith():
            return [statement.body]
        case ast.Try() | ast.TryStar():
            return [
                statement.body,
                statement.orelse,
                statement.finalbody,
                *(handler.body for handler in statement.handlers),
            ]
        case ast.Match():
            return [case.body for case in statement.cases]
        case _:
            return []
