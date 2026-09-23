from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.mixed_migration_phases import MixedMigrationPhases


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


MIGRATION = Path("db/migrations/004_transition.sql")
ATOMICITY_DIRECTIVE = (
    "-- sarj-migration-atomicity: lock=exclusive DDL lock bounded by 5 seconds; "
    "runtime=production rehearsal completed in 30 seconds; "
    "rollback=restore the previous column from snapshot OPS-812; "
    "postcondition=SELECT count(*) of null normalized values returns zero\n"
)
MIXED_PHASES = (
    "ALTER TABLE credential ADD COLUMN token TEXT;\n"
    "UPDATE credential SET token = legacy_token;\n"
    "ALTER TABLE credential DROP COLUMN legacy_token;\n"
)
INCOMPLETE_MARKER = "TO" + "DO"


def _check(source: str, path: Path = MIGRATION) -> list[Diagnostic]:
    return MixedMigrationPhases().check(path, source)


def test_reports_backfill_followed_by_contract() -> None:
    source = """
ALTER TABLE credential ADD COLUMN token TEXT;
UPDATE credential SET token = legacy_token;
ALTER TABLE credential DROP COLUMN legacy_token;
"""
    [finding] = _check(source)
    assert finding.line == 4
    assert "BACKFILL" in finding.message
    assert "CONTRACT" in finding.message


def test_accepts_complete_reviewed_atomicity_evidence_in_header() -> None:
    assert _check(ATOMICITY_DIRECTIVE + MIXED_PHASES) == []


def test_accepts_semicolon_inside_substantive_evidence_value() -> None:
    directive = ATOMICITY_DIRECTIVE.replace(
        "production rehearsal completed in 30 seconds",
        "production rehearsal completed in 30 seconds; batch stayed below one minute",
    )
    assert _check(directive + MIXED_PHASES) == []


@pytest.mark.parametrize("missing", ["lock", "runtime", "rollback", "postcondition"])
def test_incomplete_atomicity_evidence_does_not_hide_a_finding(missing: str) -> None:
    parts = ATOMICITY_DIRECTIVE.removeprefix("-- sarj-migration-atomicity: ").split("; ")
    incomplete = "; ".join(part for part in parts if not part.startswith(f"{missing}="))
    assert len(_check("-- sarj-migration-atomicity: " + incomplete + MIXED_PHASES)) == 1


def test_rejects_duplicate_or_placeholder_atomicity_evidence() -> None:
    duplicate = ATOMICITY_DIRECTIVE.replace("rollback=", "lock=another lock; rollback=")
    unknown = ATOMICITY_DIRECTIVE.replace("rollback=", "approval=claimed approval; rollback=")
    placeholder = ATOMICITY_DIRECTIVE.replace(
        "production rehearsal completed in 30 seconds",
        INCOMPLETE_MARKER,
    )
    assert len(_check(duplicate + MIXED_PHASES)) == 1
    assert len(_check(unknown + MIXED_PHASES)) == 1
    assert len(_check(placeholder + MIXED_PHASES)) == 1


def test_late_atomicity_directive_cannot_hide_a_finding() -> None:
    first_statement = "ALTER TABLE credential ADD COLUMN token TEXT;\n"
    assert len(_check(first_statement + ATOMICITY_DIRECTIVE + MIXED_PHASES)) == 1


def test_directive_in_sql_literal_or_down_section_is_not_header_evidence() -> None:
    literal = "SELECT '-- sarj-migration-atomicity: lock=x; runtime=x; rollback=x; postcondition=x';\n"
    down_section = "-- migrate:down\n" + ATOMICITY_DIRECTIVE + "-- migrate:up\n"
    assert len(_check(literal + MIXED_PHASES)) == 1
    assert len(_check(down_section + MIXED_PHASES)) == 1


def test_reports_third_substantive_phase_once() -> None:
    source = """
ALTER TABLE account ADD COLUMN normalized TEXT;
UPDATE account SET normalized = lower(name);
ALTER TABLE account VALIDATE CONSTRAINT account_normalized_check;
"""
    assert len(_check(source)) == 1


def test_folds_fresh_table_seed_indexes_and_constraints_into_expand() -> None:
    source = """
CREATE TABLE status (id UUID PRIMARY KEY, name TEXT NOT NULL);
INSERT INTO status VALUES ('00000000-0000-0000-0000-000000000001', 'ready');
CREATE INDEX status_name_idx ON status(name);
ALTER TABLE status ADD CONSTRAINT status_name_unique UNIQUE(name);
"""
    assert _check(source) == []


def test_ignores_down_section() -> None:
    source = """
-- migrate:up
ALTER TABLE account ADD COLUMN normalized TEXT;
-- migrate:down
UPDATE account SET name = normalized;
ALTER TABLE account DROP COLUMN normalized;
"""
    assert _check(source) == []


def test_ignores_keywords_in_comments_literals_and_dollar_bodies() -> None:
    source = """
CREATE TABLE note (body TEXT);
COMMENT ON TABLE note IS 'UPDATE old SET value = 1; DROP TABLE old';
DO $$ BEGIN UPDATE old SET value = 1; DROP TABLE old; END $$;
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(Path("queries/report.sql"), id="query-directory"),
        pytest.param(Path("tests/migrations/004.sql"), id="test-migration"),
        pytest.param(Path("schema.sql"), id="schema-file"),
    ],
)
def test_excludes_non_production_migration_sources(path: Path) -> None:
    source = "UPDATE account SET name = normalized; ALTER TABLE account DROP COLUMN normalized;"
    assert _check(source, path) == []


def test_clickhouse_exchange_is_contract() -> None:
    source = """-- dialect: clickhouse
INSERT INTO audit_new SELECT * FROM audit;
EXCHANGE TABLES audit AND audit_new;
"""
    [finding] = _check(source, Path("clickhouse/migrations/004.sql"))
    assert "CONTRACT" in finding.message
