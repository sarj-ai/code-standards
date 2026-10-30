from pathlib import Path

import pytest

from sarj_sql_lint.rules.no_noop_migration_down import NoNoopMigrationDown


MIGRATION = Path("migrations/001.sql")
UP = "-- migrate:up\nCREATE TABLE IF NOT EXISTS work (id UUID PRIMARY KEY);\n"


@pytest.mark.parametrize(
    "body",
    [
        "",
        "-- Retain this table when rolling back.\n",
        "/* intentionally empty */",
        "SELECT 1;",
        "SELECT NULL, false, 'rollback', -1 AS result;",
        "SET LOCAL lock_timeout = '5s'; SET LOCAL statement_timeout = '60s';",
        "BEGIN; SELECT 1; COMMIT;",
        "DO $$ BEGIN NULL; END $$;",
        "DO $rollback$ BEGIN /* noop */ NULL; NULL; END $rollback$;",
        "DO LANGUAGE plpgsql $$ BEGIN NULL; END $$;",
        "DO $$ BEGIN NULL; END $$ LANGUAGE plpgsql;",
        "RESET ALL; SELECT 1;",
    ],
)
def test_reports_proven_noop_down_sections(body: str) -> None:
    [finding] = NoNoopMigrationDown().check(MIGRATION, f"{UP}-- migrate:down\n{body}")
    assert finding.code == "SARJ127"
    assert finding.line == 3


@pytest.mark.parametrize(
    "body",
    [
        "DROP TABLE IF EXISTS work;",
        "DELETE FROM work WHERE id IS NOT NULL;",
        "UPDATE work SET id = NULL;",
        "SELECT rollback_work();",
        "SELECT pg_catalog.set_config('search_path', 'public', false);",
        "SELECT 1 FROM work;",
        "WITH deleted AS (DELETE FROM work RETURNING *) SELECT 1;",
        "DO $$ BEGIN RAISE EXCEPTION 'irreversible migration'; END $$;",
        "DO $$ BEGIN EXECUTE 'DROP TABLE work'; END $$;",
        "SELECT 1 / 0;",
        "SELECT invalid syntax !;",
        "SELECT 'unterminated;",
    ],
)
def test_preserves_substantive_or_unproven_down_sections(body: str) -> None:
    assert NoNoopMigrationDown().check(MIGRATION, f"{UP}-- migrate:down\n{body}") == []


@pytest.mark.parametrize("runner", ["+goose ", "+migrate "])
def test_supports_goose_and_sql_migrate_sections(runner: str) -> None:
    source = f"-- {runner}Up\nCREATE TABLE work (id UUID);\n-- {runner}Down\nSELECT 1;"
    assert len(NoNoopMigrationDown().check(MIGRATION, source)) == 1


def test_rollback_file_is_checked_without_a_section_marker() -> None:
    findings = NoNoopMigrationDown().check(Path("migrations/001.down.sql"), "SELECT 1;")
    assert len(findings) == 1


@pytest.mark.parametrize(
    "source",
    [
        "SELECT '-- migrate:down';",
        "SELECT $$\n-- migrate:down\nSELECT 1;\n$$;",
        "/*\n-- migrate:down\nSELECT 1;\n*/",
        "DO $$ BEGIN\n-- migrate:down\nNULL; END $$;",
        "SELECT 1; -- migrate:down\nSELECT 1;",
        "-- migrate:up\nSELECT 1;",
    ],
)
def test_data_comments_and_procedural_bodies_cannot_create_down_sections(source: str) -> None:
    assert NoNoopMigrationDown().check(MIGRATION, source) == []


def test_each_down_section_is_evaluated_independently() -> None:
    source = UP + "-- migrate:down\nSELECT 1;\n-- migrate:up\nSELECT 2;\n-- migrate:down\nDROP TABLE work;"
    findings = NoNoopMigrationDown().check(MIGRATION, source)
    assert [finding.line for finding in findings] == [3]


def test_noop_literal_with_semicolon_does_not_split_statements() -> None:
    assert len(NoNoopMigrationDown().check(MIGRATION, UP + "-- migrate:down\nSELECT ';';")) == 1


def test_schema_dump_is_excluded() -> None:
    assert NoNoopMigrationDown().check(Path("schema.sql"), "-- migrate:down\nSELECT 1;") == []
