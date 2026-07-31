from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sarj_sql_lint.rules.idempotent_ddl import IdempotentDdl


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return IdempotentDdl().check(Path("migration.sql"), source)


def test_flags_create_table_without_if_not_exists():
    src = "CREATE TABLE orders (id BIGSERIAL PRIMARY KEY);"
    assert len(_check(src)) == 1


def test_allows_create_table_if_not_exists():
    src = "CREATE TABLE IF NOT EXISTS orders (id BIGSERIAL PRIMARY KEY);"
    assert _check(src) == []


def test_flags_create_temp_table():
    src = "CREATE TEMP TABLE scratch (id INT);"
    assert len(_check(src)) == 1


def test_flags_create_unlogged_table():
    src = "CREATE UNLOGGED TABLE cache (id INT);"
    assert len(_check(src)) == 1


def test_flags_create_global_temporary_table():
    src = "CREATE GLOBAL TEMPORARY TABLE scratch (id INT);"
    assert len(_check(src)) == 1


def test_allows_temp_table_if_not_exists():
    src = "CREATE TEMP TABLE IF NOT EXISTS scratch (id INT);"
    assert _check(src) == []


def test_flags_add_column_without_if_not_exists():
    src = "ALTER TABLE orders ADD COLUMN note TEXT;"
    assert len(_check(src)) == 1


def test_allows_add_column_if_not_exists():
    src = "ALTER TABLE orders ADD COLUMN IF NOT EXISTS note TEXT;"
    assert _check(src) == []


def test_flags_create_index_without_if_not_exists():
    src = "CREATE INDEX idx_orders_user ON orders(user_id);"
    assert len(_check(src)) == 1


def test_flags_create_unique_index_without_if_not_exists():
    src = "CREATE UNIQUE INDEX idx_orders_user ON orders(user_id);"
    assert len(_check(src)) == 1


def test_allows_create_index_if_not_exists():
    src = "CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);"
    assert _check(src) == []


def test_allows_create_index_concurrently_if_not_exists():
    src = "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_u ON orders(user_id);"
    assert _check(src) == []


def test_flags_create_extension_without_if_not_exists():
    src = "CREATE EXTENSION pgcrypto;"
    assert len(_check(src)) == 1


def test_allows_create_extension_if_not_exists():
    src = "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
    assert _check(src) == []


def test_flags_create_schema_sequence_without_if_not_exists():
    src = """
CREATE SCHEMA billing;
CREATE SEQUENCE order_seq;
"""
    assert len(_check(src)) == 2


def test_ignores_create_type_which_has_no_if_not_exists_in_postgres():
    # Postgres `CREATE TYPE` has no IF NOT EXISTS form, so demanding it would ask
    # for invalid SQL. Enums are handled by SARJ103; idempotency for composite
    # types is a guard (DROP TYPE IF EXISTS) the linter doesn't mandate here.
    src = "CREATE TYPE color AS (r INT, g INT, b INT);"
    assert _check(src) == []


def test_allows_schema_sequence_with_if_not_exists():
    src = """
CREATE SCHEMA IF NOT EXISTS billing;
CREATE SEQUENCE IF NOT EXISTS order_seq;
"""
    assert _check(src) == []


def test_flags_drop_table_without_if_exists():
    src = "DROP TABLE orders;"
    assert len(_check(src)) == 1


def test_flags_drop_index_without_if_exists():
    src = "DROP INDEX idx_orders_user;"
    assert len(_check(src)) == 1


def test_allows_drop_with_if_exists():
    src = """
DROP TABLE IF EXISTS orders;
DROP INDEX IF EXISTS idx_orders_user;
DROP INDEX CONCURRENTLY IF EXISTS idx_orders_user;
"""
    assert _check(src) == []


def test_is_case_insensitive():
    src = "create table orders (id bigserial primary key);"
    assert len(_check(src)) == 1


def test_flags_each_violation_in_multi_statement_file():
    src = """
CREATE TABLE orders (id BIGSERIAL PRIMARY KEY);
ALTER TABLE orders ADD COLUMN note TEXT;
CREATE INDEX idx_orders_note ON orders(note);
DROP TABLE legacy_orders;
"""
    assert len(_check(src)) == 4


def test_skips_comment_lines():
    src = """
-- CREATE TABLE orders was dropped here; DROP TABLE orders too
/* CREATE INDEX idx ON orders(user_id); */
CREATE TABLE IF NOT EXISTS orders (id BIGSERIAL PRIMARY KEY);
"""
    assert _check(src) == []


def test_skips_trailing_inline_comment():
    src = "CREATE TABLE IF NOT EXISTS orders (id INT); -- DROP TABLE orders later"
    assert _check(src) == []


def test_flags_create_table_inside_dollar_quoted_body():
    """A `$$ ... $$` body is live SQL, not string data — the rule must see into it.

    This previously asserted the opposite. `mask_sql` blanked dollar-quoted bodies
    as though they were string literals, which hid 26 live DDL/DML keywords across
    12 files of the two-repo first-party corpus from all 8 rules. A `CREATE TABLE`
    without `IF NOT EXISTS` inside a function body is exactly as non-idempotent as
    one at the top level — the second call fails — so it must be flagged.
    """
    src = """
CREATE OR REPLACE FUNCTION seed() RETURNS void AS $$
BEGIN
    CREATE TABLE staging (id INT);
END
$$ LANGUAGE plpgsql;
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 4


def test_string_literal_inside_a_dollar_quoted_body_is_still_masked():
    """Keeping the body as SQL must not stop its own string literals being masked."""
    src = """
CREATE OR REPLACE FUNCTION seed() RETURNS void AS $$
BEGIN
    RAISE NOTICE 'CREATE TABLE staging (id INT);';
END
$$ LANGUAGE plpgsql;
"""
    assert _check(src) == []


# --- MySQL implements only some of the IF [NOT] EXISTS forms ----------------------
#
# MySQL has no `CREATE INDEX IF NOT EXISTS`, no `ADD COLUMN IF NOT EXISTS` and no
# `DROP INDEX IF EXISTS`, so demanding them there demands a syntax error. It DOES
# have `CREATE TABLE IF NOT EXISTS`, `CREATE SCHEMA IF NOT EXISTS` and
# `DROP TABLE IF EXISTS`, and so does SQLite — which is why the gate is `is_mysql`
# and not `not is_postgres`.

_MYSQL_MARKER = "CREATE TABLE IF NOT EXISTS `k` (`id` int UNSIGNED) ENGINE=InnoDB;\n"


def test_allows_mysql_add_column_without_if_not_exists():
    assert _check(_MYSQL_MARKER + "ALTER TABLE `orders` ADD COLUMN `note` text;") == []


def test_allows_mysql_create_index_without_if_not_exists():
    assert _check(_MYSQL_MARKER + "CREATE INDEX `idx` ON `orders` (`user_id`);") == []


def test_allows_mysql_drop_index_without_if_exists():
    assert _check(_MYSQL_MARKER + "DROP INDEX `idx` ON `orders`;") == []


def test_flags_mysql_create_table_without_if_not_exists():
    """The boundary: MySQL *does* support this one, so the gate must not reach it."""
    src = "CREATE TABLE `orders` (`id` int UNSIGNED NOT NULL) ENGINE=InnoDB;"
    assert len(_check(src)) == 1


def test_flags_mysql_drop_table_without_if_exists():
    """The boundary: MySQL *does* support `DROP TABLE IF EXISTS`."""
    assert len(_check(_MYSQL_MARKER + "DROP TABLE `orders`;")) == 1


def test_flags_sqlite_create_index_without_if_not_exists():
    """The boundary: SQLite supports `CREATE INDEX IF NOT EXISTS`, so it is a real finding.

    Backticks alone prove "not Postgres" — they must not be read as "MySQL".
    """
    src = "CREATE INDEX `idx` ON `orders` (`user_id`);"
    assert len(_check(src)) == 1


def test_allows_sqlite_add_column_without_unsupported_if_not_exists():
    src = "-- dialect: sqlite\nALTER TABLE orders ADD COLUMN note TEXT;"
    assert _check(src) == []


def test_explicit_sqlite_still_requires_idempotent_create_index():
    src = "-- dialect: sqlite\nCREATE INDEX idx ON orders (user_id);"
    assert len(_check(src)) == 1


def test_generated_migration_is_redirected_not_silenced(tmp_path: Path) -> None:
    root = tmp_path / "prisma" / "migrations"
    (root / "20240101000000_init").mkdir(parents=True)
    (root / "migration_lock.toml").write_text('provider = "postgresql"\n')
    migration = root / "20240101000000_init" / "migration.sql"
    src = 'CREATE TABLE "User" ("id" TEXT NOT NULL);'
    migration.write_text(src)

    diags = IdempotentDdl().check(migration, src)
    assert len(diags) == 1
    assert "generator-owned" in diags[0].message
