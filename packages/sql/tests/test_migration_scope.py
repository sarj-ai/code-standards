"""Shared production-PostgreSQL migration scope."""

from pathlib import Path

import pytest

from sarj_sql_lint.rule_base import is_postgres_migration


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (Path("supabase/migrations/001.sql"), "INSERT INTO t VALUES (1);"),
        (Path("db/migrations/001.sql"), "-- migrate:up\nINSERT INTO t VALUES (1);"),
        (Path("db/migration/V1__users.sql"), "-- dialect: postgresql\nALTER TABLE users ADD COLUMN name TEXT;"),
        (Path("stdin"), "-- +goose Up\nALTER TABLE users ADD COLUMN id UUID;"),
        (Path("changesets/users.sql"), "-- liquibase formatted sql\nALTER TABLE users ADD COLUMN id UUID;"),
    ],
)
def test_accepts_positive_migration_and_postgres_evidence(path: Path, source: str) -> None:
    assert is_postgres_migration(path, source)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (Path("queries/users.sql"), "ALTER TABLE users ADD COLUMN id UUID;"),
        (Path("fixtures/migrations/001.sql"), "-- migrate:up\nALTER TABLE users ADD COLUMN id UUID;"),
        (Path("snapshots/migrations/001.sql"), "-- migrate:up\nALTER TABLE users ADD COLUMN id UUID;"),
        (Path("d1/migrations/001.sql"), "-- migrate:up\nALTER TABLE users ADD COLUMN id UUID;"),
        (Path("db/migrations/001.sql"), "ALTER TABLE users ADD COLUMN name TEXT;"),
        (Path("db/migrations/001.sql"), "-- dialect: sqlite\nALTER TABLE users ADD COLUMN id UUID;"),
    ],
)
def test_rejects_ambiguous_nonproduction_or_nonpostgres_sql(path: Path, source: str) -> None:
    assert not is_postgres_migration(path, source)


@pytest.mark.parametrize(
    "source",
    [
        "-- an example uses AUTO_INCREMENT\n-- migrate:up\nALTER TABLE users ADD COLUMN id UUID;",
        "-- migrate:up\nSELECT 'AUTO_INCREMENT';\nALTER TABLE users ADD COLUMN id UUID;",
    ],
)
def test_nonpostgres_tokens_in_comments_or_strings_do_not_override_live_postgres(source: str) -> None:
    assert is_postgres_migration(Path("db/migrations/001.sql"), source)
