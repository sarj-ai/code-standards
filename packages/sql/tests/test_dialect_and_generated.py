"""Test shared scope predicates: is_postgres, is_mysql, is_generated_migration."""

from __future__ import annotations

from pathlib import Path

import pytest

from sarj_sql_lint.rule_base import (
    Diagnostic,
    clear_path_caches,
    declared_dialect,
    is_generated_migration,
    is_mysql,
    is_postgres,
    is_sqlite,
    mask_sql,
    redirect_to_model,
)


@pytest.mark.parametrize(
    "source",
    [
        "CREATE TABLE `users` (`id` int);",  # backtick-quoted identifier
        "CREATE TABLE users (id int NOT NULL AUTO_INCREMENT);",
        "CREATE TABLE t (id integer PRIMARY KEY AUTOINCREMENT);",
        "CREATE TABLE t (id int) ENGINE=InnoDB;",
        "CREATE TABLE t (id int) ENGINE = MyISAM;",
        "CREATE TABLE t (name varchar(10) COLLATE utf8mb4_unicode_ci);",
        "CREATE TABLE t (id int UNSIGNED);",
    ],
)
def test_dialect_markers_are_recognised(source: str) -> None:
    assert not is_postgres(source)


@pytest.mark.parametrize(
    "source",
    [
        'CREATE TABLE "users" (id BIGSERIAL PRIMARY KEY);',
        "CREATE TABLE users (payload JSONB NOT NULL);",
        "CREATE INDEX CONCURRENTLY idx ON users USING gin (payload);",
        "ALTER TABLE users ALTER COLUMN id TYPE bigint USING id::bigint;",
        "CREATE TABLE users (created_at TIMESTAMPTZ DEFAULT now());",
    ],
)
def test_postgres_ddl_is_not_mistaken_for_another_dialect(source: str) -> None:
    assert is_postgres(source)


def test_a_backtick_inside_a_comment_does_not_change_the_dialect() -> None:
    """Rules pass masked text precisely so prose cannot fake a dialect."""
    source = "-- the `users` table\nCREATE TABLE users (id BIGSERIAL);"
    assert is_postgres(mask_sql(source))


def test_a_backtick_inside_a_string_literal_does_not_change_the_dialect() -> None:
    source = "INSERT INTO doc (body) VALUES ('see `users`');"
    assert is_postgres(mask_sql(source))


@pytest.mark.parametrize(
    ("directive", "expected"),
    [
        ("-- dialect: sqlite", "sqlite"),
        ("-- sql-dialect: PostgreSQL", "postgresql"),
        ("-- dialect: mariadb", "mysql"),
    ],
)
def test_explicit_dialect_directive(directive: str, expected: str) -> None:
    source = f"{directive}\nCREATE TABLE example (id INTEGER);"
    assert declared_dialect(source) == expected
    assert is_postgres(source) is (expected == "postgresql")
    assert is_sqlite(source) is (expected == "sqlite")


def test_free_form_dialect_prose_is_not_a_directive() -> None:
    source = "-- This migration also runs on sqlite\nCREATE TABLE example (id BIGSERIAL);"
    assert declared_dialect(source) is None
    assert is_postgres(source)


def test_sqlite_is_not_postgres_but_is_not_mysql_either() -> None:
    """SARJ102 depends on this: SQLite supports `CREATE TABLE/INDEX IF NOT EXISTS`."""
    source = "CREATE TABLE `t` (`id` integer PRIMARY KEY AUTOINCREMENT);"
    assert not is_postgres(source)
    assert not is_mysql(source)


@pytest.mark.parametrize(
    "source",
    [
        "CREATE TABLE t (id int NOT NULL AUTO_INCREMENT);",
        "CREATE TABLE t (id int) ENGINE=InnoDB;",
        "CREATE TABLE t (id int UNSIGNED);",
        "INSERT INTO t VALUES (1) ON DUPLICATE KEY UPDATE id = 1;",
        "ALTER TABLE t MODIFY COLUMN name text;",
    ],
)
def test_mysql_markers_are_recognised(source: str) -> None:
    assert is_mysql(source)


def test_drizzle_statement_breakpoint_is_a_content_sentinel() -> None:
    source = 'CREATE TABLE "a" ();\n--> statement-breakpoint\nCREATE TABLE "b" ();\n'
    assert is_generated_migration(Path("0000_init.sql"), source)


def test_prisma_migration_lock_marks_the_whole_tree(tmp_path: Path) -> None:
    root = tmp_path / "prisma" / "migrations"
    (root / "20240101000000_init").mkdir(parents=True)
    (root / "migration_lock.toml").write_text('provider = "postgresql"\n')
    migration = root / "20240101000000_init" / "migration.sql"
    migration.write_text("CREATE TABLE a ();")
    assert is_generated_migration(migration, migration.read_text())


def test_generated_marker_cache_can_be_cleared_between_lint_runs(tmp_path: Path) -> None:
    migration = tmp_path / "migration.sql"
    migration.write_text("CREATE TABLE a ();", encoding="utf-8")
    clear_path_caches()
    assert not is_generated_migration(migration, migration.read_text(encoding="utf-8"))

    (tmp_path / "migration_lock.toml").write_text('provider = "postgresql"\n', encoding="utf-8")
    clear_path_caches()

    assert is_generated_migration(migration, migration.read_text(encoding="utf-8"))


def test_atlas_sum_marks_the_tree(tmp_path: Path) -> None:
    root = tmp_path / "migrations"
    root.mkdir(parents=True)
    (root / "atlas.sum").write_text("h1:abc\n")
    migration = root / "20240101000000.sql"
    migration.write_text("CREATE TABLE a ();")
    assert is_generated_migration(migration, migration.read_text())


def test_drizzle_journal_marks_the_tree(tmp_path: Path) -> None:
    root = tmp_path / "drizzle"
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "_journal.json").write_text("{}")
    migration = root / "0000_init.sql"
    migration.write_text("CREATE TABLE a ();")
    assert is_generated_migration(migration, migration.read_text())


def test_a_hand_written_migration_tree_is_not_generated(tmp_path: Path) -> None:
    """The boundary: no marker, no sentinel — the rule speaks normally."""
    root = tmp_path / "db" / "migrations"
    root.mkdir(parents=True)
    migration = root / "20240101000000_add_users.sql"
    migration.write_text("CREATE TABLE a ();")
    assert not is_generated_migration(migration, migration.read_text())


def test_the_marker_search_stops_at_a_repository_boundary(tmp_path: Path) -> None:
    """A marker in a *different* project above the checkout must not leak downward."""
    (tmp_path / "migration_lock.toml").write_text('provider = "postgresql"\n')
    repo = tmp_path / "other_repo"
    (repo / ".git").mkdir(parents=True)
    root = repo / "db" / "migrations"
    root.mkdir(parents=True)
    migration = root / "20240101000000_add_users.sql"
    migration.write_text("CREATE TABLE a ();")
    assert not is_generated_migration(migration, migration.read_text())


def test_redirect_keeps_every_finding_and_renames_the_fix_site() -> None:
    diags = [Diagnostic(Path("m.sql"), 1, 1, "SARJ101", "Use `TIMESTAMPTZ`.")]
    out = redirect_to_model(diags, model_owned=True)
    assert len(out) == 1
    assert out[0].line == 1
    assert out[0].message.startswith("Use `TIMESTAMPTZ`.")
    assert "schema.prisma" in out[0].message


def test_redirect_is_a_no_op_on_a_hand_written_migration() -> None:
    diags = [Diagnostic(Path("m.sql"), 1, 1, "SARJ101", "Use `TIMESTAMPTZ`.")]
    assert redirect_to_model(diags, model_owned=False) == diags
