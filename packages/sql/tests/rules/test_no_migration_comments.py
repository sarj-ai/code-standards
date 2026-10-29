from pathlib import Path

import pytest

from sarj_sql_lint.rules.no_migration_comments import NoMigrationComments


MIGRATION = Path("migrations/001.sql")


@pytest.mark.parametrize(
    "source",
    [
        "-- Enforced in the application, between 1 and 10.\nSELECT 1;",
        "CREATE TABLE settings (n INTEGER); -- required; capped 1..10",
        "/* Keep this invariant intact. */ SELECT 1;",
        "/* outer /* nested */ comment */ SELECT 1;",
        "SELECT 1; -- sarj-noqa: SARJ128",
        "SELECT 1; -- sarj-noqa",
        "-- sarj-migration-atomicity: lock=bounded\nSELECT 1;",
        "COMMENT ON COLUMN settings.n IS 'positive';",
        "COMMENT ON TABLE settings IS NULL;",
        "DO $$ BEGIN /* executable comment */ NULL; END $$;",
        "DO $$ BEGIN COMMENT ON TABLE t IS 'prose'; END $$;",
        "-- migrate:up this is a prose suffix\nSELECT 1;",
        "SELECT 1; -- migrate:up",
        "/* migrate:up */ SELECT 1;",
    ],
)
def test_reports_all_non_executable_comments(source: str) -> None:
    [finding] = NoMigrationComments().check(MIGRATION, source)
    assert finding.code == "SARJ128"


@pytest.mark.parametrize(
    "directive",
    [
        "migrate:up",
        "migrate:down transaction:false",
        "+goose Up",
        "+goose Down",
        "+goose StatementBegin",
        "+goose StatementEnd",
        "+goose NO TRANSACTION",
        "+goose ENVSUB ON",
        "+migrate Up notransaction",
        "+migrate Down",
        "liquibase formatted sql",
        "changeset app:001 runOnChange:true",
        "rollback DROP TABLE IF EXISTS settings;",
        "dialect: postgresql",
        "sql-dialect: sqlite",
        "atlas:txmode none",
        "> statement-breakpoint",
    ],
)
def test_preserves_exact_standalone_execution_directives(directive: str) -> None:
    assert NoMigrationComments().check(MIGRATION, f"-- {directive}\nSELECT 1;") == []


def test_strings_identifiers_and_scalar_dollar_data_are_not_comments() -> None:
    source = (
        "SELECT '-- prose', '/* prose */', $$-- data$$, $outer$/* data */$outer$;\n"
        'CREATE TABLE settings ("-- label" TEXT, "COMMENT ON" TEXT);\n'
    )
    assert NoMigrationComments().check(MIGRATION, source) == []


def test_reports_individual_comments_once_at_their_own_location() -> None:
    source = "-- migrate:up\nSELECT 1; -- inline\n/* block\ncomment */\nCOMMENT ON TABLE t IS 'text';"
    findings = NoMigrationComments().check(MIGRATION, source)
    assert [(finding.line, finding.col) for finding in findings] == [(2, 11), (3, 1), (5, 1)]


def test_generated_migration_reports_comments_at_the_owning_model() -> None:
    findings = NoMigrationComments().check(MIGRATION, "--> statement-breakpoint\n-- narrative\nSELECT 1;")
    assert len(findings) == 1
    assert "generator-owned" in findings[0].message


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(Path("queries/lookup.sql"), id="query-file"),
        pytest.param(Path("schema.sql"), id="schema-dump"),
        pytest.param(Path("structure.sql"), id="structure-dump"),
    ],
)
def test_excludes_non_migration_sources_and_dumps(path: Path) -> None:
    assert NoMigrationComments().check(path, "-- schema context\nSELECT 1;") == []


def test_copy_payload_is_data_and_copy_literals_do_not_hide_comments() -> None:
    payload = "COPY settings (body) FROM STDIN;\n-- literal data\nCOMMENT ON TABLE t IS 'data';\n\\.\n"
    assert NoMigrationComments().check(MIGRATION, payload) == []
    [finding] = NoMigrationComments().check(MIGRATION, "-- real comment\nSELECT 'COPY FROM STDIN';")
    assert finding.line == 1


def test_copy_data_cannot_forge_dump_provenance_or_erase_prior_comments() -> None:
    source = "-- real comment\nCOPY settings(body) FROM STDIN;\n-- PostgreSQL database dump\n\\.\n"
    [finding] = NoMigrationComments().check(MIGRATION, source)
    assert finding.line == 1
