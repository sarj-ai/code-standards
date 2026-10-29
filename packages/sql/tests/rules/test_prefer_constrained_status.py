from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rule_base import DefaultLevel
from sarj_sql_lint.rules.prefer_constrained_status import PreferConstrainedStatus


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


_PATH = Path("supabase/migrations/001_job.sql")


def _check(source: str, path: Path = _PATH) -> list[Diagnostic]:
    return PreferConstrainedStatus().check(path, source)


@pytest.mark.parametrize(
    "example",
    PreferConstrainedStatus.public_examples(),
    ids=tuple(item.example_id for item in PreferConstrainedStatus.public_examples()),
)
def test_documented_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, Path(example.focus_file.path))) == example.expected_count


@pytest.mark.parametrize(
    "check",
    [
        "NOT confirmed OR requested",
        "NOT (confirmed AND requested)",
        "confirmed <> requested",
        "confirmed = requested",
        "confirmed IS TRUE AND requested IS FALSE OR confirmed IS FALSE",
    ],
)
def test_flags_proven_restrictions_between_required_flags(check: str) -> None:
    source = f"CREATE TABLE job (requested BOOLEAN NOT NULL, confirmed BOOLEAN NOT NULL, CHECK ({check}));"
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ129"
    assert findings[0].severity is DefaultLevel.WARNING
    assert "confirmed, requested" in findings[0].message


@pytest.mark.parametrize(
    "check",
    [
        "confirmed OR NOT confirmed OR requested",
        "confirmed AND NOT confirmed AND requested",
        "confirmed AND requested",
        "confirmed OR (requested AND NOT requested)",
        "confirmed IS NULL OR requested",
        "custom(confirmed, requested)",
        "requested = 1 OR confirmed",
    ],
)
def test_abstains_for_independent_tautological_impossible_or_unknown_checks(check: str) -> None:
    assert _check(f"CREATE TABLE job (requested BOOLEAN NOT NULL, confirmed BOOLEAN NOT NULL, CHECK ({check}));") == []


@pytest.mark.parametrize("nullable", ["requested BOOLEAN", "requested INTEGER NOT NULL"])
def test_unproven_boolean_domain_is_not_guessed(nullable: str) -> None:
    assert (
        _check(f"CREATE TABLE job ({nullable}, confirmed BOOLEAN NOT NULL, CHECK (NOT confirmed OR requested));") == []
    )


def test_quoted_columns_have_exact_case_and_diagnostics_have_source_offsets() -> None:
    source = '-- migrate:up\nSELECT 1;\nCREATE TABLE job (\n  "Request" BOOLEAN NOT NULL,\n  "confirm)ed" BOOLEAN NOT NULL,\n  CHECK (NOT "confirm)ed" OR "Request")\n);'
    (finding,) = _check(source)
    assert (finding.line, finding.col) == (4, 3)
    assert '"Request"' in finding.message


@pytest.mark.parametrize("other", ["NOT b OR a", "a"])
def test_interacting_checks_cause_abstention(other: str) -> None:
    assert (
        _check(f"CREATE TABLE job (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b), CHECK ({other}));") == []
    )


@pytest.mark.parametrize(
    "source",
    [
        "-- CREATE TABLE t (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b));",
        "SELECT $$CREATE TABLE t (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b));$$;",
        "DO $$ BEGIN CREATE TABLE t (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b)); END $$;",
        "CREATE TABLE t (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b);",
    ],
)
def test_comments_literals_routines_and_malformed_input_are_inert(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path", ["queries/job.sql", "postgres/tests/migrations/job.sql", "mysql/migrations/job.sql", "supabase/schema.sql"]
)
def test_scope_exclusions(path: str) -> None:
    assert _check("CREATE TABLE t (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b));", Path(path)) == []


def test_unrelated_tables_and_string_predicates_do_not_prove_flag_dependence() -> None:
    source = "CREATE TABLE a (flag BOOLEAN NOT NULL); CREATE TABLE b (other BOOLEAN NOT NULL, CHECK (flag OR other));"
    assert _check(source) == []


def test_copy_input_cannot_manufacture_a_schema_contract() -> None:
    assert (
        _check(
            "COPY docs FROM STDIN;\nCREATE TABLE t (a BOOLEAN NOT NULL, b BOOLEAN NOT NULL, CHECK (NOT a OR b));\n\\.\n"
        )
        == []
    )
