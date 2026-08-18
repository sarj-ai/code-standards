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
    sql_comments,
)


if TYPE_CHECKING:
    from pathlib import Path


_SQL_HEAD_RE = re.compile(
    r"^(?:ALTER|BEGIN|COMMIT|CREATE|DELETE|DROP|GRANT|INSERT|MERGE|REVOKE|ROLLBACK|SELECT|SET|TRUNCATE|UPDATE|WITH)\b",
    re.IGNORECASE,
)
_COMPLETE_SQL_RE = re.compile(
    r"^(?:"
    r"(?:ALTER|CREATE)\s+(?:TABLE|TYPE|INDEX|VIEW|SCHEMA|FUNCTION|PROCEDURE)\s+[\w.\"]+|"
    r"(?:DELETE\s+FROM|DROP\s+(?:TABLE|TYPE|INDEX|VIEW|SCHEMA)|INSERT\s+INTO|UPDATE\s+[\w.\"]+\s+SET)\b|"
    r"SELECT\b.+\bFROM\b|(?:BEGIN|COMMIT|ROLLBACK|TRUNCATE)\s*;?$"
    r")",
    re.IGNORECASE,
)
_BANNER_RE = re.compile(r"^(?:[-=#*~_.+ ]{4,}|.*(?:={4,}|-{4,}|#{4,}|\*{4,}|~{4,}).*)$")
_DEBT_MARKERS = ("TO" + "DO", "FIX" + "ME", "HACK", "X" + "XX")
_DEBT_RE = re.compile(r"^(?:" + "|".join(_DEBT_MARKERS) + r")\b", re.IGNORECASE)
_REFERENCE_RE = re.compile(r"https?://|\b(?:RFC|CVE|[A-Z][A-Z0-9]{1,9})[- ]?\d+\b|#\d{2,6}\b")
_DIRECTIVE_RE = re.compile(
    r"^(?:sarj-noqa|sqlfluff|noqa|dialect\s*:|sql-dialect\s*:|migrate:|\+goose|liquibase|pg_dump)",
    re.IGNORECASE,
)


@final
class NoCommentCruft(Rule):
    id = "no-comment-cruft"
    code = "SARJ113"
    documentation = RuleDocumentation(
        summary="Commented-out SQL, decorative banners, and untracked debt markers must be removed.",
        rationale="Disabled statements drift from executable migrations while version control already preserves their history.",
        remediation="Delete disabled SQL and decorative dividers; retain only current constraints, rollback instructions, and owned references.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "The scanner distinguishes SQL comments from strings, identifiers, and executable dollar-quoted bodies.",
            "Dialect, migration, dump, lint, rollback, and externally referenced comments are preserved.",
        ),
        examples=(
            RuleExample(
                example_id="commented-statement",
                title="Disabled SQL statement",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.sql("migrations/001.sql", "-- DROP TABLE legacy_events;\nSELECT 1;\n"),),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="rollback-instruction",
                title="Rollback instruction records an operational constraint",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql("migrations/001.sql", "-- Roll back by restoring snapshot OPS-812.\nSELECT 1;\n"),
                ),
                focus_path=PurePosixPath("migrations/001.sql"),
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
        findings: list[Diagnostic] = []
        for comment in sql_comments(source):
            lines = [line.strip().lstrip("*").strip() for line in comment.body.splitlines()]
            effective = [line for line in lines if line]
            if not effective or any(_DIRECTIVE_RE.match(line) for line in effective):
                continue
            message = _message(effective)
            if message is None:
                continue
            findings.append(Diagnostic(path, comment.line, comment.column, self.code, message))
        return findings


def _message(lines: list[str]) -> str | None:
    if any(_BANNER_RE.fullmatch(line) for line in lines):
        return "Section-banner comment — use migration statements and file structure instead of ASCII dividers."
    code_lines = sum(_SQL_HEAD_RE.match(line) is not None for line in lines)
    if code_lines and code_lines * 2 >= len(lines) and any(_COMPLETE_SQL_RE.match(line) for line in lines):
        return "Commented-out SQL — delete it; version control preserves migration history."
    if any(_DEBT_RE.match(line) and _REFERENCE_RE.search(line) is None for line in lines):
        return "Unowned SQL debt marker — resolve it or attach a durable issue reference."
    return None
