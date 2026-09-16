from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.mixed_migration_phases import MixedMigrationPhases


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


MIGRATION = Path("db/migrations/004_transition.sql")


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
