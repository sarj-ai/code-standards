from pathlib import Path

import pytest

from sarj_sql_lint.__main__ import analyze
from sarj_sql_lint.rule_base import (
    declared_dialect,
    is_mysql,
    is_postgres,
    is_postgres_migration,
    is_postgres_source,
    is_sqlite,
)


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


_OPAQUE_DIALECT_CASES = (
    ("plain-string", "SELECT '\n-- dialect: sqlite\n';\n"),
    ("dollar-string", "SELECT $doc$\n-- dialect: sqlite\n$doc$;\n"),
    ("identifier", 'SELECT "\n-- dialect: sqlite\n";\n'),
    ("backtick", "SELECT `\n-- dialect: sqlite\n`;\n"),
    ("bracket", "SELECT [\n-- dialect: sqlite\n];\n"),
    ("block", "/*\n-- dialect: sqlite\n*/ SELECT 1;\n"),
    ("nested-block", "/* outer /* inner */\n-- dialect: sqlite\n*/ SELECT 1;\n"),
    ("documentation", "-- documentation mentions -- dialect: sqlite\nSELECT 1;\n"),
    ("executable-do", "DO $$ BEGIN\n-- dialect: sqlite\nNULL; END $$;\n"),
    (
        "executable-function",
        "CREATE FUNCTION public_example() RETURNS int AS $body$\n-- dialect: sqlite\nSELECT 1;\n$body$ LANGUAGE SQL;\n",
    ),
)


@pytest.mark.parametrize(
    ("name", "source"), _OPAQUE_DIALECT_CASES, ids=tuple(item[0] for item in _OPAQUE_DIALECT_CASES)
)
@pytest.mark.parametrize("crlf", [False, True])
def test_dialect_metadata_requires_a_file_comment(name: str, source: str, *, crlf: bool) -> None:
    source = source.replace("\n", "\r\n") if crlf else source
    assert declared_dialect(source) is None, name
    assert declared_dialect(f"{source}-- sql-dialect: postgresql\n") == "postgresql"
    assert declared_dialect(f"{source}-- dialect: sqlite\n") == "sqlite"


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        ("-- dialect: postgres", "postgresql"),
        ("-- sql-dialect: postgresql", "postgresql"),
        ("-- DIALECT: SQLITE", "sqlite"),
        ("-- dialect: mysql", "mysql"),
        ("-- dialect: mariadb", "mysql"),
    ],
)
def test_true_dialect_comments_keep_supported_aliases(marker: str, expected: str) -> None:
    assert declared_dialect(f"{marker}\nSELECT 1;") == expected
    assert declared_dialect(f"{marker}\n-- dialect: sqlite\n") == expected


@pytest.mark.parametrize(
    "source",
    [
        "SELECT 'UUID';\nALTER TABLE public_example ADD COLUMN name TEXT;\n",
        'SELECT "UUID";\nALTER TABLE public_example ADD COLUMN name TEXT;\n',
        "SELECT $doc$UUID$doc$;\nALTER TABLE public_example ADD COLUMN name TEXT;\n",
        "-- docs mention UUID\nALTER TABLE public_example ADD COLUMN name TEXT;\n",
    ],
)
def test_migration_dialect_evidence_excludes_source_data(source: str, tmp_path: Path) -> None:
    path = tmp_path / "db/migrations/001.sql"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert not is_postgres_source(path, source)
    assert not is_postgres_migration(path, source)
    assert analyze(["require-lock-timeout"], [path]) == []


@pytest.mark.parametrize(
    "source",
    [
        "ALTER TABLE public_example ADD COLUMN id UUID;\n",
        "DO $$ BEGIN NULL; END $$;\n",
        "CREATE FUNCTION public_example() RETURNS int AS $$ SELECT 1; $$ LANGUAGE SQL;\n",
    ],
)
def test_live_postgresql_type_and_executable_bodies_keep_evidence(source: str) -> None:
    assert is_postgres_source(Path("db/migrations/001.sql"), source)


@pytest.mark.parametrize("word", ["AUTO_INCREMENT", "AUTOINCREMENT", "UNSIGNED"])
def test_scalar_dollar_data_does_not_infer_a_foreign_dialect(word: str) -> None:
    source = f"SELECT $doc${word}$doc$;\nALTER TABLE public_example ADD COLUMN id UUID;\n"
    assert is_postgres(source)
    assert not is_mysql(source)
    assert not is_sqlite(source)
    assert is_postgres_source(Path("db/migrations/001.sql"), source)


def test_fake_sqlite_dialect_does_not_hide_actual_pg_migration_findings(tmp_path: Path) -> None:
    source = "SELECT $doc$\n-- dialect: sqlite\n$doc$;\nALTER TABLE public_example ADD COLUMN id UUID;\n"
    path = tmp_path / "db/migrations/001.sql"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    findings = analyze(["require-lock-timeout"], [path])
    assert len(findings) == 1
    assert findings[0].line == 4
    assert findings == analyze(["require-lock-timeout"], [path])


@pytest.mark.parametrize(
    "source",
    ["SELECT `AUTO_INCREMENT` FROM event;", "SELECT `AUTOINCREMENT` FROM event;", "SELECT `UNSIGNED` FROM event;"],
)
def test_cross_dialect_identifier_words_are_not_live_dialect_features(source: str) -> None:
    assert not is_mysql(source)
    assert not is_sqlite(source)
    assert not is_postgres(source)


@pytest.mark.parametrize(
    "source",
    [
        "SELECT '\n-- dialect: sqlite\n",
        "SELECT $doc$\n-- dialect: sqlite\n",
        'SELECT "\n-- dialect: sqlite\n',
        "SELECT `\n-- dialect: sqlite\n",
        "SELECT [\n-- dialect: sqlite\n",
        "/*\n-- dialect: sqlite\n",
    ],
)
def test_incomplete_values_cannot_admit_a_dialect_directive(source: str) -> None:
    assert declared_dialect(source) is None


def test_dialect_cache_is_bounded_and_content_sensitive() -> None:
    source = "SELECT $doc$\n-- dialect: sqlite\n$doc$;\n"
    assert declared_dialect(source) is None
    assert declared_dialect(f"{source}-- dialect: mysql\n") == "mysql"
    assert declared_dialect(source) is None
    assert declared_dialect.cache_info().maxsize == 32
