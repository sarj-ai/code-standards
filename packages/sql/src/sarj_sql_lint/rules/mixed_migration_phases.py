from __future__ import annotations

from enum import StrEnum
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    dollar_quoted_spans,
    is_dump_file,
    is_generated_migration,
    is_migration_source,
    mask_sql,
    mask_sql_literals_and_comments,
    normalize_sql_identifier,
    source_location,
    split_statements,
)


if TYPE_CHECKING:
    from pathlib import Path


_NON_PRODUCTION_PARTS = frozenset({"test", "tests", "testing", "__tests__"})
_SECTION_DIRECTIVE = re.compile(r"^\s*--\s*(?:migrate:|\+goose\s+)(up|down)\b", re.IGNORECASE)
_IDENT = (
    r'(?:(?:"(?:""|[^"\n])+")|[A-Za-z_][A-Za-z0-9_$]*)(?:\s*\.\s*(?:(?:"(?:""|[^"\n])+")|[A-Za-z_][A-Za-z0-9_$]*))*'
)
_CREATE_TABLE = re.compile(
    rf"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<table>{_IDENT})(?=\s|\(|;|$)",
    re.IGNORECASE,
)
_INSERT = re.compile(rf"^\s*(?:INSERT\s+INTO|COPY)\s+(?P<table>{_IDENT})(?=\s|\(|;|$)", re.IGNORECASE)
_ALTER_TABLE = re.compile(
    rf"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?P<table>{_IDENT})(?=\s|\(|;|$)(?P<body>[\s\S]*)",
    re.IGNORECASE,
)
_NORMALIZE_SPACE = re.compile(r"\s+")
_PHASE_REVIEW_LIMIT = 3


class _Phase(StrEnum):
    EXPAND = "EXPAND"
    BACKFILL = "BACKFILL"
    ENFORCE = "ENFORCE"
    CONTRACT = "CONTRACT"


@final
class MixedMigrationPhases(Rule):
    id = "mixed-migration-phases"
    code = "SARJ119"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Review existing-table migrations that combine backfill, enforcement, and contract phases.",
        rationale=(
            "Combining data movement with destructive or enforcing schema changes removes deployment checkpoints and "
            "makes lock duration, rollback, and compatibility harder to control."
        ),
        remediation=(
            "Split expand, backfill, enforcement, and contract work into independently deployable migrations. "
            "Review atomicity, locking, runtime and rollback requirements in the change description."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only authored production migration forward sections are checked; generated migrations, dumps, tests, fixtures, schemas, and rollback sections are excluded.",
            "Fresh-table seed data, indexes, and constraints are folded into the table's expand phase.",
            "Dollar-quoted procedure and anonymous-block bodies and dynamically executed SQL are intentionally ignored.",
            "The rule reports BACKFILL plus CONTRACT or three distinct phases; two-phase expand/backfill and backfill/enforce migrations remain reviewable without a finding.",
            "Header comments cannot waive phase findings; operational review belongs in the change description.",
        ),
        examples=(
            RuleExample(
                example_id="rename-backfill-contract",
                title="An existing-table backfill immediately removes its legacy column",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/004_credentials.sql",
                        "ALTER TABLE credential ADD COLUMN token TEXT;\n"
                        "UPDATE credential SET token = legacy_token;\n"
                        "ALTER TABLE credential DROP COLUMN legacy_token;\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/004_credentials.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="fresh-table-bootstrap",
                title="A fresh lookup table is created, seeded, and indexed atomically",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/004_status.sql",
                        "CREATE TABLE status (id UUID PRIMARY KEY, name TEXT NOT NULL);\n"
                        "INSERT INTO status VALUES ('00000000-0000-0000-0000-000000000001', 'ready');\n"
                        "CREATE INDEX status_name_idx ON status(name);\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/004_status.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        parts = {part.casefold() for part in path.parts}
        if (
            parts & _NON_PRODUCTION_PARTS
            or not is_migration_source(path, source)
            or is_dump_file(source, path)
            or is_generated_migration(path, source)
        ):
            return []
        forward = _forward_section(source)
        masked = _mask_dollar_bodies(forward, mask_sql_literals_and_comments(forward, mask_dollar_literals=True))
        return _find_mixed_phase_diagnostic(path, masked, self.code)


def _find_mixed_phase_diagnostic(path: Path, masked: str, code: str) -> list[Diagnostic]:
    phases: set[_Phase] = set()
    first_lines: dict[_Phase, int] = {}
    fresh_tables: set[str] = set()
    for statement in split_statements(masked):
        text = "\n".join(fragment.text for fragment in statement).strip()
        if not text:
            continue
        phase = _classify(text, fresh_tables)
        if phase is None:
            continue
        line = next((fragment.line for fragment in statement if fragment.text.strip()), statement[0].line)
        phases.add(phase)
        first_lines.setdefault(phase, line)
        if _requires_phase_review(phases):
            ordered = sorted(phases, key=lambda item: first_lines[item])
            detail = ", ".join(f"{item.value} at line {first_lines[item]}" for item in ordered)
            return [
                Diagnostic(
                    path,
                    line,
                    max(1, len(statement[0].text) - len(statement[0].text.lstrip()) + 1),
                    code,
                    f"Forward migration mixes deployment phases ({detail}). Split independently deployable "
                    "phases and review atomicity, locking, runtime and rollback in the change description.",
                    severity=DefaultLevel.WARNING,
                )
            ]
    return []


def _forward_section(source: str) -> str:
    dollar_lines = {
        line
        for start, end in dollar_quoted_spans(source)
        for line in range(source_location(source, start).line, source_location(source, max(start, end - 1)).line + 1)
    }
    lines = source.splitlines(keepends=True)
    has_up = any(
        line_number not in dollar_lines
        and (match := _SECTION_DIRECTIVE.match(line)) is not None
        and match.group(1).casefold() == "up"
        for line_number, line in enumerate(lines, start=1)
    )
    active = not has_up
    output: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        match = None if line_number in dollar_lines else _SECTION_DIRECTIVE.match(line)
        if match is not None:
            active = match.group(1).casefold() == "up"
        output.append(line if active else re.sub(r"[^\r\n]", " ", line))
    return "".join(output)


def _mask_dollar_bodies(source: str, masked: str) -> str:
    output = list(masked)
    for start, end in dollar_quoted_spans(source):
        for position in range(start, end):
            if output[position] not in "\r\n":
                output[position] = " "
    return "".join(output)


def _classify(statement: str, fresh_tables: set[str]) -> _Phase | None:
    normalized = statement.strip()
    upper = _NORMALIZE_SPACE.sub(" ", normalized).upper()
    if match := _CREATE_TABLE.match(normalized):
        if "IF NOT EXISTS" not in _NORMALIZE_SPACE.sub(" ", normalized[: match.start("table")]).upper():
            fresh_tables.add(normalize_sql_identifier(match.group("table")))
        return _Phase.EXPAND
    if match := _INSERT.match(normalized):
        return _Phase.EXPAND if normalize_sql_identifier(match.group("table")) in fresh_tables else _Phase.BACKFILL
    if upper.startswith(("UPDATE ", "DELETE ", "MERGE ")):
        return _Phase.BACKFILL
    if upper.startswith(("EXCHANGE TABLES ", "RENAME TABLE ")):
        return _Phase.CONTRACT
    if upper.startswith("DROP "):
        return (
            None
            if re.match(r"DROP\s+(?:TABLE|FUNCTION)\s+(?:IF\s+EXISTS\s+)?(?:PG_TEMP\.)", upper)
            else _Phase.CONTRACT
        )
    if match := _ALTER_TABLE.match(normalized):
        return _alter_phase(match, fresh_tables)
    if upper.startswith(("CREATE ", "COMMENT ON ")):
        return _Phase.EXPAND
    return None


def _alter_phase(match: re.Match[str], fresh_tables: set[str]) -> _Phase:
    table = normalize_sql_identifier(match.group("table"))
    body = _NORMALIZE_SPACE.sub(" ", mask_sql(match.group("body"))).upper()
    if table in fresh_tables:
        return _Phase.EXPAND
    if re.search(r"\b(?:DROP|RENAME)\b|\b(?:ALTER\s+COLUMN\s+)?TYPE\b|\bSET\s+DATA\s+TYPE\b", body):
        return _Phase.CONTRACT
    if re.search(r"\bVALIDATE\s+CONSTRAINT\b|\bSET\s+NOT\s+NULL\b", body) or (
        "ADD CONSTRAINT" in body and "NOT VALID" not in body
    ):
        return _Phase.ENFORCE
    return _Phase.EXPAND


def _requires_phase_review(phases: set[_Phase]) -> bool:
    return (_Phase.BACKFILL in phases and _Phase.CONTRACT in phases) or len(phases) >= _PHASE_REVIEW_LIMIT
