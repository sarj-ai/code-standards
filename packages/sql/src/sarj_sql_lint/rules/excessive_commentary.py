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
    SourceComment,
    is_dump_file,
    is_migration_source,
    sql_comments,
)


if TYPE_CHECKING:
    from pathlib import Path


_MIN_LINES = 4
_MIN_WORDS = 28
_ABSOLUTE_LINES = 10
_ABSOLUTE_WORDS = 70
_ANCHOR_RE = re.compile(
    r"https?://|`[^`]+`|\b(?:RFC|CVE|[A-Z][A-Z0-9]{1,9})[- ]?\d+\b|#\d+|"
    r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b|@>|->>|"
    r"\b(?:lock|rollback|restore|backfill|replica|deadlock|timeout|security|permission|transaction)\b|"
    r"\b\d+\s*(?:ms|s|seconds?|minutes?|hours?|rows?|bytes?|kb|mb|gb)\b",
    re.IGNORECASE,
)
_DIRECTIVE_RE = re.compile(r"^(?:sarj-noqa|sqlfluff|noqa|dialect\s*:|migrate:|\+goose|liquibase)", re.IGNORECASE)
_RATIONALE_RE = re.compile(
    r"\b(?:because|otherwise|therefore|must|never|cannot|can't|required?|requires|would|"
    r"rather than|so\s+(?:that|a|an|the|this|it|we|they)|invariant|constraint|compatibility|drift)\b",
    re.IGNORECASE,
)


@final
class ExcessiveCommentary(Rule):
    id = "excessive-commentary"
    code = "SARJ115"
    documentation = RuleDocumentation(
        summary="Long migration commentary — express schema intent in DDL and retain only operational constraints.",
        rationale="Narrative migration prose obscures executable schema changes and can drift from the DDL it describes.",
        remediation="Delete narration; retain concise rollback, locking, data-loss, compatibility, and security constraints.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only authored migration comment blocks with at least four non-empty lines and 28 words are inspected.",
            "Schema dumps and directives are excluded; references, rationale, lists, and operational constraints are preserved unless one block exceeds ten lines and 70 words.",
        ),
        examples=(
            RuleExample(
                example_id="ddl-narration",
                title="Migration comments narrate the table declarations",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001.sql",
                        "-- Create the integration table used by the application.\n"
                        "-- The table stores every custom integration row.\n"
                        "-- The next statement defines the identifier and name.\n"
                        "-- The final statement creates the table in the database.\n"
                        "CREATE TABLE IF NOT EXISTS integration (id BIGINT PRIMARY KEY, name TEXT);\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="rollback-constraint",
                title="Rollback and locking guidance remains local",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001.sql",
                        "-- Keep lock_timeout at 3 seconds because API-812 writes continuously.\n"
                        "-- Roll back by dropping the new index concurrently.\n"
                        "SET lock_timeout = '3s';\nSELECT 1;\n",
                    ),
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
        if is_dump_file(source, path) or not is_migration_source(path, source):
            return []
        findings: list[Diagnostic] = []
        for group in _comment_groups(source):
            lines = tuple(
                line.strip().lstrip("*").strip()
                for comment in group
                for line in comment.body.splitlines()
                if line.strip().lstrip("*").strip()
            )
            text = "\n".join(lines)
            words = len(text.split())
            absolutely_excessive = len(lines) >= _ABSOLUTE_LINES and words >= _ABSOLUTE_WORDS
            if len(lines) < _MIN_LINES or words < _MIN_WORDS or any(_DIRECTIVE_RE.match(line) for line in lines):
                continue
            if not absolutely_excessive and (_ANCHOR_RE.search(text) or _RATIONALE_RE.search(text)):
                continue
            if not absolutely_excessive and any(re.match(r"^(?:[-*+] |\d+[.)] )", line) for line in lines):
                continue
            first = group[0]
            findings.append(Diagnostic(path, first.line, first.column, self.code, self.description))
        return findings


def _comment_groups(source: str) -> list[list[SourceComment]]:
    groups: list[list[SourceComment]] = []
    for comment in sql_comments(source):
        if groups and not comment.block and not groups[-1][-1].block and comment.line == groups[-1][-1].line + 1:
            groups[-1].append(comment)
        else:
            groups.append([comment])
    return groups
