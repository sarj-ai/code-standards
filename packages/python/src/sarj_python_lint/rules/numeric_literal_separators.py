from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_python_lint._fixes import python_source_hash
from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Fix,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    TextEdit,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_DECIMAL = re.compile(r"(?P<integer>[0-9][0-9_]*)(?P<fraction>\.[0-9_]*)?\Z")
_MIN_GROUPED_DIGITS = 5
_GROUP_WIDTH = 3


@final
class NumericLiteralSeparators(Rule):
    id = "numeric-literal-separators"
    code = "SARJ567"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Group long decimal numeric literals with thousands separators.",
        rationale="Long ungrouped decimal quantities are harder to read and easy to miscount.",
        remediation="Use three-digit groups such as 10_000_000; retain a named constant when the value has domain meaning.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Decimal integer parts with at least five digits are checked; four-digit years, base-prefixed numbers, exponents, imaginary numbers, fractional digits, comments and strings are left alone.",
            "Safe fixes change numeric token spelling only and preserve the parsed AST. Interpolated strings are review-only because changing a debug expression also changes its displayed label.",
            "Generated files and exact-code suppressions are respected. No constant names or numeric domains are invented.",
        ),
        examples=(
            RuleExample(
                example_id="undeclared-domain",
                title="The contract is implicit",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/service.py", "RATE = 16000\n"),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declared-domain",
                title="The contract is explicit",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/service.py", "RATE = 16_000\n"),),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.tree is None or context.generated:
            return []
        findings: list[Diagnostic] = []
        source_lines = tuple(line.encode("utf-8") for line in context.source_lines)
        digest: str | None = None
        for node in context.nodes(ast.Constant):
            if context.suppressions.is_suppressed(node.lineno, self.code):
                continue
            replacement = _grouped_literal(node, source_lines)
            if replacement is None:
                continue
            if digest is None:
                digest = python_source_hash(context.source)
            findings.append(
                Diagnostic(
                    context.path,
                    node.lineno,
                    node.col_offset + 1,
                    self.code,
                    f"Group this decimal literal as {replacement}.",
                    severity=Severity.WARNING,
                    fixes=_literal_fixes(node, replacement, digest, context),
                )
            )
        return findings


def _grouped_literal(node: ast.Constant, source_lines: tuple[bytes, ...]) -> str | None:
    if type(node.value) not in {int, float}:
        return None
    if node.end_lineno != node.lineno or node.end_col_offset is None:
        return None
    token = source_lines[node.lineno - 1][node.col_offset : node.end_col_offset].decode("utf-8")
    match = _DECIMAL.fullmatch(token)
    if match is None:
        return None
    integer = match["integer"].replace("_", "")
    if len(integer) < _MIN_GROUPED_DIGITS:
        return None
    groups = [integer[max(0, end - _GROUP_WIDTH) : end] for end in range(len(integer), 0, -_GROUP_WIDTH)]
    replacement = "_".join(reversed(groups)) + (match["fraction"] or "")
    return replacement if replacement != token else None


def _literal_fixes(node: ast.Constant, replacement: str, digest: str, context: PythonFileContext) -> tuple[Fix, ...]:
    if node.end_lineno is None or node.end_col_offset is None or _interpolated(node, context):
        return ()
    return (
        Fix(
            "Group decimal digits",
            AutofixPolicy.SAFE,
            digest,
            (TextEdit(node.lineno, node.col_offset + 1, node.end_lineno, node.end_col_offset + 1, replacement),),
        ),
    )


def _interpolated(node: ast.AST, context: PythonFileContext) -> bool:
    current = context.parents.get(node)
    while current is not None:
        if isinstance(current, ast.JoinedStr | ast.TemplateStr):
            return True
        current = context.parents.get(current)
    return False
