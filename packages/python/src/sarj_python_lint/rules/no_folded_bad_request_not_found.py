from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, final, override

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
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_BAD_REQUEST = 400
_NOT_FOUND = 404
_FOLDED = frozenset({_BAD_REQUEST, _NOT_FOUND})
_STATUS_NAMES: Final[dict[str, int]] = {
    "BAD_REQUEST": _BAD_REQUEST,
    "HTTP_400_BAD_REQUEST": _BAD_REQUEST,
    "NOT_FOUND": _NOT_FOUND,
    "HTTP_404_NOT_FOUND": _NOT_FOUND,
}
_STATUS_OWNERS = frozenset({"HTTPStatus", "status"})
_MESSAGE = (
    "HTTP 400 and 404 share one branch, so a rejected request is handled like a missing record. "
    "Handle 404 alone and raise the 400 as a non-retriable error."
)


@final
class NoFoldedBadRequestNotFound(Rule):
    id = "no-folded-bad-request-not-found"
    code = "SARJ498"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Do not handle HTTP 400 and 404 statuses in one branch.",
        rationale=(
            "A 400 means the request or its configuration is wrong; folding it into the not-found path makes a "
            "misconfiguration log success with an empty result, indistinguishable from a deleted record."
        ),
        remediation="Give 404 its own branch and raise the 400 as a non-retriable client error.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Membership tests against a literal collection, `or` chains of equality on one subject, and match "
                "or-patterns are checked when they name both 400 and 404 as integers or recognized status constants."
            ),
            "Statuses held in variables or named constants other than the HTTPStatus and Starlette names are not resolved.",
            "Test modules are excluded because parametrized cases list statuses together.",
        ),
        examples=(
            RuleExample(
                example_id="folded-membership",
                title="A 400 is treated as not found",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "client/records.py",
                        "def fetch(response):\n"
                        "    if response.status_code in (400, 404):\n"
                        "        return None\n"
                        "    return response.json()\n",
                    ),
                ),
                focus_path=PurePosixPath("client/records.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="separate-branches",
                title="Not found and bad request are separate outcomes",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "client/records.py",
                        "def fetch(response):\n"
                        "    if response.status_code == 404:\n"
                        "        return None\n"
                        "    if response.status_code == 400:\n"
                        "        raise ValueError(response.text)\n"
                        "    return response.json()\n",
                    ),
                ),
                focus_path=PurePosixPath("client/records.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated or is_test_path(context.path):
            return []
        if not ("400" in context.symbol_source or "BAD_REQUEST" in context.symbol_source):
            return []
        locations = {
            (node.lineno, node.col_offset + 1)
            for node in context.nodes(ast.Compare, ast.BoolOp)
            if _is_folded_membership(node) or _is_folded_equality_chain(node)
        }
        locations.update(
            (node.lineno, node.col_offset + 1) for node in context.nodes(ast.MatchOr) if _is_folded_pattern(node)
        )
        return [
            Diagnostic(context.path, line, column, self.code, _MESSAGE, severity=Severity.WARNING)
            for line, column in sorted(locations)
        ]


def _is_folded_membership(node: ast.expr) -> bool:
    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.In):
        return False
    collection = node.comparators[0]
    if not isinstance(collection, (ast.Tuple, ast.List, ast.Set)):
        return False
    return {_status(element) for element in collection.elts} >= _FOLDED


def _is_folded_equality_chain(node: ast.expr) -> bool:
    if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
        return False
    statuses_by_subject: dict[str, set[int | None]] = {}
    for value in node.values:
        if isinstance(value, ast.Compare) and len(value.ops) == 1 and isinstance(value.ops[0], ast.Eq):
            subject = ast.dump(value.left)
            statuses_by_subject.setdefault(subject, set()).add(_status(value.comparators[0]))
    return any(statuses >= _FOLDED for statuses in statuses_by_subject.values())


def _is_folded_pattern(node: ast.MatchOr) -> bool:
    statuses = {_status(pattern.value) for pattern in node.patterns if isinstance(pattern, ast.MatchValue)}
    return statuses >= _FOLDED


def _status(node: ast.expr) -> int | None:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in _STATUS_OWNERS:
        return _STATUS_NAMES.get(node.attr)
    return None
