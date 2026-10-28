from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_sql_lint.__main__ import analyze, main
from sarj_sql_lint.rule_base import DefaultLevel
from sarj_sql_lint.rules.combine_alter_table import CombineAlterTable


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


P = Path("supabase/migrations/001_retire_version.sql")
_ORIGINAL = """\
ALTER TABLE call DROP CONSTRAINT IF EXISTS call_scenario_version_fkey;
ALTER TABLE call DROP COLUMN IF EXISTS scenario_version_id;
ALTER TABLE custom_scenario DROP CONSTRAINT IF EXISTS custom_scenario_applied_version_fkey;
ALTER TABLE custom_scenario DROP CONSTRAINT IF EXISTS custom_scenario_pending_language_version_fkey;
ALTER TABLE custom_scenario DROP COLUMN IF EXISTS applied_version_id;
ALTER TABLE custom_scenario DROP COLUMN IF EXISTS in_use_by;
ALTER TABLE custom_scenario DROP COLUMN IF EXISTS in_use_since;
ALTER TABLE custom_scenario DROP COLUMN IF EXISTS pending_language_version_id;
ALTER TABLE custom_scenario DROP COLUMN IF EXISTS pending_language_settings;
DROP INDEX IF EXISTS idx_scenario_version_history;
DROP TABLE IF EXISTS scenario_version;
"""
_COMPRESSED = """\
ALTER TABLE call
    DROP CONSTRAINT IF EXISTS call_scenario_version_fkey,
    DROP COLUMN IF EXISTS scenario_version_id;
ALTER TABLE custom_scenario
    DROP CONSTRAINT IF EXISTS custom_scenario_applied_version_fkey,
    DROP CONSTRAINT IF EXISTS custom_scenario_pending_language_version_fkey,
    DROP COLUMN IF EXISTS applied_version_id,
    DROP COLUMN IF EXISTS in_use_by,
    DROP COLUMN IF EXISTS in_use_since,
    DROP COLUMN IF EXISTS pending_language_version_id,
    DROP COLUMN IF EXISTS pending_language_settings;
DROP INDEX IF EXISTS idx_scenario_version_history;
DROP TABLE IF EXISTS scenario_version;
"""


def _check(source: str, path: Path = P) -> list[Diagnostic]:
    return CombineAlterTable().check(path, source)


def test_documented_examples() -> None:
    verify_native_rule(CombineAlterTable, analyze)


def test_requested_migration_compresses_nine_alter_statements_into_two() -> None:
    findings = _check(_ORIGINAL)
    assert [finding.line for finding in findings] == [2, 4, 5, 6, 7, 8, 9]
    assert all(finding.code == "SARJ123" and finding.severity is DefaultLevel.ERROR for finding in findings)
    assert "line 1" in findings[0].message
    assert all("line 3" in finding.message for finding in findings[1:])
    assert _check(_COMPRESSED) == []


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("DROP COLUMN a", "DROP COLUMN b"),
        ("DROP a CASCADE", "DROP b RESTRICT"),
        ("DROP CONSTRAINT IF EXISTS a", "DROP COLUMN IF EXISTS a"),
        ("ADD COLUMN a TEXT", "ADD COLUMN b BIGINT"),
        ("ADD IF NOT EXISTS a UUID", "ADD COLUMN IF NOT EXISTS b TIMESTAMP WITH TIME ZONE"),
        ("ADD COLUMN a DOUBLE PRECISION", "ADD COLUMN b BOOLEAN"),
        ("ALTER COLUMN a SET NOT NULL", "ALTER b SET NOT NULL"),
        ("ALTER COLUMN a DROP NOT NULL", "ALTER COLUMN b DROP NOT NULL"),
        ("ALTER COLUMN a DROP DEFAULT", "ALTER COLUMN b DROP DEFAULT"),
        ("DROP COLUMN a, DROP COLUMN b", "DROP CONSTRAINT c, DROP COLUMN d"),
    ],
)
def test_recognized_independent_actions_combine(first: str, second: str) -> None:
    assert len(_check(f"ALTER TABLE item {first};\nALTER TABLE item {second};")) == 1


@pytest.mark.parametrize(
    "header",
    ["item", "public.item", '"public"."item"', "IF EXISTS item", "ONLY item", "IF EXISTS ONLY item", "item *"],
)
def test_identical_relation_modifiers_are_preserved(header: str) -> None:
    assert len(_check(f"ALTER TABLE {header} DROP COLUMN a; ALTER TABLE {header} DROP COLUMN b;")) == 1


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("item", "public.item"),
        ("public.item", "other.item"),
        ('"Item"', "item"),
        ("item", "IF EXISTS item"),
        ("item", "ONLY item"),
        ("item", "item *"),
        ("ONLY item", "item *"),
        ("IF EXISTS ONLY item", "ONLY item"),
    ],
)
def test_distinct_relation_identity_or_modifiers_do_not_combine(first: str, second: str) -> None:
    assert _check(f"ALTER TABLE {first} DROP COLUMN a; ALTER TABLE {second} DROP COLUMN b;") == []


@pytest.mark.parametrize(
    ("first", "second"),
    [("ITEM", '"item"'), ('"schema;name"."item"', '"schema;name"."item"'), ('"item""archive"', '"item""archive"')],
)
def test_postgres_identifier_identity_and_quoted_delimiters(first: str, second: str) -> None:
    source = f"ALTER TABLE {first} DROP COLUMN a; ALTER TABLE {second} DROP COLUMN b;"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "between",
    [
        "UPDATE item SET a = NULL;",
        "INSERT INTO item DEFAULT VALUES;",
        "DELETE FROM item;",
        "SELECT lock_table();",
        "SET search_path = other;",
        "SET LOCAL lock_timeout = '5s';",
        "COMMIT; BEGIN;",
        "ALTER TABLE other DROP COLUMN legacy;",
        "ALTER TABLE item RENAME COLUMN a TO b;",
        "ALTER TABLE item SET SCHEMA archive;",
        "ALTER TABLE item ATTACH PARTITION part FOR VALUES IN (1);",
        "ALTER TABLE item DETACH PARTITION part;",
        "ALTER TABLE item VALIDATE CONSTRAINT valid;",
        "DO $$ BEGIN ALTER TABLE item DROP COLUMN c; END $$;",
        "SELECT $$ALTER TABLE item DROP COLUMN c;$$;",
        "unexpected SQL;",
        "ALTER TABLE item DROP COLUMN a (;",
    ],
)
def test_any_intervening_statement_ends_combination_proof(between: str) -> None:
    assert _check(f"ALTER TABLE item DROP COLUMN a;\n{between}\nALTER TABLE item DROP COLUMN b;") == []


@pytest.mark.parametrize(
    "boundary",
    ["-- migrate:down", "-- migrate:up", "-- +goose Down", "-- +goose Up", "--changeset owner:2"],
)
def test_migration_sections_are_independent(boundary: str) -> None:
    source = f"ALTER TABLE item DROP COLUMN a;\n{boundary}\nALTER TABLE item DROP COLUMN b;"
    assert _check(source) == []


def test_ordinary_comments_and_whitespace_do_not_break_a_group() -> None:
    source = "ALTER TABLE item DROP COLUMN a;\n-- retire remaining legacy fields\n/* rationale */\nALTER TABLE item DROP COLUMN b;"
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("DROP COLUMN a", "DROP COLUMN a"),
        ("ADD COLUMN a TEXT", "ADD COLUMN a BIGINT"),
        ("ALTER a SET NOT NULL", "ALTER a SET NOT NULL"),
        ("DROP COLUMN a", "ADD COLUMN b TEXT"),
        ("ALTER a SET NOT NULL", "ALTER b DROP NOT NULL"),
        ("ALTER a TYPE BIGINT", "ALTER b TYPE BIGINT"),
        ("ALTER a TYPE INTEGER USING b", "ALTER b TYPE INTEGER USING a"),
        ("ALTER a SET DEFAULT 1", "ALTER b SET DEFAULT 1"),
        ("ADD a TEXT DEFAULT 'legacy'", "ADD b TEXT DEFAULT 'legacy'"),
        ("ADD a TEXT NOT NULL", "ADD b TEXT NOT NULL"),
        ("ADD a SERIAL", "ADD b SERIAL"),
        ("ADD a app.domain", "ADD b app.domain"),
        ("ADD a custom_type", "ADD b custom_type"),
        ("ADD a VARCHAR(20)", "ADD b VARCHAR(20)"),
        ("ADD CONSTRAINT a CHECK (id > 0) NOT VALID", "ADD CONSTRAINT b CHECK (id < 100) NOT VALID"),
        ("VALIDATE CONSTRAINT a", "VALIDATE CONSTRAINT b"),
        ("RENAME COLUMN a TO b", "RENAME COLUMN c TO d"),
    ],
)
def test_unproven_action_compatibility_remains_separate(first: str, second: str) -> None:
    assert _check(f"ALTER TABLE item {first}; ALTER TABLE item {second};") == []


@pytest.mark.parametrize(
    "source",
    [
        "ALTER TABLE item DROP COLUMN; ALTER TABLE item DROP COLUMN b;",
        "ALTER TABLE item DROP COLUMN a,; ALTER TABLE item DROP COLUMN b;",
        "ALTER TABLE item DROP COLUMN a nonsense; ALTER TABLE item DROP COLUMN b;",
        "ALTER TABLE item ADD COLUMN a; ALTER TABLE item ADD COLUMN b TEXT;",
        "ALTER TABLE item ADD COLUMN a TEXT 'literal'; ALTER TABLE item ADD COLUMN b TEXT;",
        "ALTER TABLE item DROP COLUMN a; ALTER TABLE item DROP COLUMN b (;",
        "ALTER TABLE ONLY item * DROP COLUMN a; ALTER TABLE ONLY item * DROP COLUMN b;",
        "ALTER TABLE item DROP COLUMN a, DROP COLUMN a; ALTER TABLE item DROP COLUMN b;",
    ],
)
def test_malformed_and_duplicate_actions_do_not_manufacture_proof(source: str) -> None:
    assert _check(source) == []


def test_comments_strings_and_dollar_bodies_are_not_top_level_actions() -> None:
    source = (
        "-- ALTER TABLE item DROP COLUMN a; ALTER TABLE item DROP COLUMN b;\n"
        "SELECT 'ALTER TABLE item DROP COLUMN a; ALTER TABLE item DROP COLUMN b;';\n"
        "DO $$ BEGIN ALTER TABLE item DROP COLUMN a; ALTER TABLE item DROP COLUMN b; END $$;\n"
        "SELECT $data$ALTER TABLE item DROP COLUMN a; ALTER TABLE item DROP COLUMN b;$data$;\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_locations_use_original_physical_lines_and_columns(ending: str) -> None:
    source = ending.join(["-- migration", "ALTER TABLE item DROP COLUMN a;", "  ALTER TABLE item DROP COLUMN b;"])
    findings = _check(source)
    assert len(findings) == 1
    assert (findings[0].line, findings[0].col) == (3, 3)


def test_same_line_location_points_at_repeated_statement() -> None:
    source = "ALTER TABLE item DROP COLUMN a; ALTER TABLE item DROP COLUMN b;"
    findings = _check(source)
    assert (findings[0].line, findings[0].col) == (1, source.index("ALTER", 1) + 1)


@pytest.mark.parametrize(
    ("path", "prefix"),
    [
        (Path("schema.sql"), ""),
        (Path("tests/migrations/001.sql"), ""),
        (Path("fixtures/migrations/001.sql"), ""),
        (P, "-- dialect: sqlite\n"),
        (P, "-- dialect: mysql\n"),
        (P, "-- PostgreSQL database dump\n"),
        (P, "--> statement-breakpoint\n"),
    ],
)
def test_unsupported_and_generator_owned_sources_are_excluded(path: Path, prefix: str) -> None:
    assert _check(prefix + _ORIGINAL, path) == []


def test_error_cli_and_exact_code_suppression(tmp_path: Path) -> None:
    target = tmp_path / "supabase/migrations/001.sql"
    target.parent.mkdir(parents=True)
    source = "ALTER TABLE item DROP COLUMN a;\nALTER TABLE item DROP COLUMN b;"
    target.write_text(source)
    assert main(["check", "--rule", CombineAlterTable.id, str(target)]) == 1
    target.write_text(f"{source} -- sarj-noqa: SARJ123 -- deployment tooling requires this statement boundary\n")
    assert main(["check", "--rule", CombineAlterTable.id, str(target)]) == 0
