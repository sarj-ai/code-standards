"""SARJ107: forbid `OFFSET` pagination — use cursor-based pagination."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_dump_file,
    mask_sql,
)


if TYPE_CHECKING:
    from pathlib import Path


# Match OFFSET followed by a value or parameter token across supported SQL dialects.
PATTERN = re.compile(
    r"\bOFFSET\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|\d+)",
    re.IGNORECASE,
)


@final
class NoOffsetPagination(Rule):
    """OFFSET pagination — use cursor pagination instead."""

    id = "no-offset-pagination"
    code = "SARJ107"
    documentation = RuleDocumentation(
        summary="OFFSET pagination — use cursor pagination (WHERE id > :cursor).",
        rationale="OFFSET scans and discards every skipped row, so later pages become slower as the result set grows.",
        remediation="Filter on a stable cursor column, preserve its ordering, and retain a bounded LIMIT.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        aliases=("no-limit-offset",),
        limitations=("The rule recognizes literal and common driver parameter markers following OFFSET.",),
        examples=(
            RuleExample(
                example_id="offset-pagination",
                title="Pagination that scans skipped rows",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.sql("queries/calls.sql", "SELECT id FROM call ORDER BY id LIMIT 50 OFFSET 100;\n"),),
                focus_path=PurePosixPath("queries/calls.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="cursor-pagination",
                title="Pagination bounded by a stable cursor",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "queries/calls.sql", "SELECT id FROM call WHERE id > :cursor ORDER BY id LIMIT 50;\n"
                    ),
                ),
                focus_path=PurePosixPath("queries/calls.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []

        diags: list[Diagnostic] = []
        for lineno, line in enumerate(mask_sql(source).splitlines(), start=1):
            diags.extend(
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=match.start() + 1,
                    code=self.code,
                    message=(
                        "Use cursor pagination (WHERE id > :cursor ORDER BY id "
                        "LIMIT n) — OFFSET scans and discards every skipped row."
                    ),
                )
                for match in PATTERN.finditer(line)
            )
        return diags
