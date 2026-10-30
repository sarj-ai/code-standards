from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.autofix import fix_source
from sarj_sql_lint.rules.idempotent_ddl import IdempotentDdl


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: Path = Path("db/migrations/001.sql")) -> list[Diagnostic]:
    return IdempotentDdl().check(path, source)


_PUBLIC_EXAMPLES = IdempotentDdl.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(IdempotentDdl().check(Path(focus.path), focus.source)) == example.expected_count


def test_flags_create_table_without_if_not_exists():
    src = "CREATE TABLE orders (id BIGSERIAL PRIMARY KEY);"
    assert len(_check(src)) == 1


def test_allows_create_table_if_not_exists():
    src = "CREATE TABLE IF NOT EXISTS orders (id BIGSERIAL PRIMARY KEY);"
    assert _check(src) == []


def test_flags_create_temp_table():
    src = "CREATE TEMP TABLE scratch (id INT);"
    assert len(_check(src)) == 1


def test_ignores_runtime_query_temp_table() -> None:
    src = "CREATE TEMP TABLE scratch (id INT);"
    assert _check(src, Path("queries/scratch.sql")) == []


def test_flags_multiline_create_table() -> None:
    diags = _check("CREATE\nTABLE orders (id BIGSERIAL PRIMARY KEY);")
    assert len(diags) == 1
    assert diags[0].line == 1


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
    # Postgres CREATE TYPE has no IF NOT EXISTS clause, so it is ignored by this rule.
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
    src = """
CREATE OR REPLACE FUNCTION seed() RETURNS void AS $$
BEGIN
    RAISE NOTICE 'CREATE TABLE staging (id INT);';
END
$$ LANGUAGE plpgsql;
"""
    assert _check(src) == []


# MySQL supports only a subset of IF [NOT] EXISTS clauses.

_MYSQL_MARKER = "CREATE TABLE IF NOT EXISTS `k` (`id` int UNSIGNED) ENGINE=InnoDB;\n"


def test_allows_mysql_add_column_without_if_not_exists():
    assert _check(f"{_MYSQL_MARKER}ALTER TABLE `orders` ADD COLUMN `note` text;") == []


def test_allows_mysql_create_index_without_if_not_exists():
    assert _check(f"{_MYSQL_MARKER}CREATE INDEX `idx` ON `orders` (`user_id`);") == []


def test_allows_mysql_drop_index_without_if_exists():
    assert _check(f"{_MYSQL_MARKER}DROP INDEX `idx` ON `orders`;") == []


def test_flags_mysql_create_table_without_if_not_exists():
    src = "CREATE TABLE `orders` (`id` int UNSIGNED NOT NULL) ENGINE=InnoDB;"
    assert len(_check(src)) == 1


def test_flags_mysql_drop_table_without_if_exists():
    assert len(_check(f"{_MYSQL_MARKER}DROP TABLE `orders`;")) == 1


def test_flags_sqlite_create_index_without_if_not_exists():
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


@pytest.mark.parametrize(
    "constraint",
    [
        "ADD CONSTRAINT orders_customer_fk FOREIGN KEY (customer_id) REFERENCES customers (id) NOT VALID",
        "ADD CONSTRAINT orders_total_check CHECK (total >= 0)",
        "DROP CONSTRAINT IF EXISTS orders_customer_fk",
    ],
)
def test_native_constraint_ddl_does_not_require_a_catalog_wrapper(constraint: str) -> None:
    assert _check(f"-- migrate:up\nALTER TABLE orders {constraint};\n-- migrate:down\n") == []


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE MATERIALIZED VIEW totals AS SELECT 1 AS total",
        "CREATE FOREIGN TABLE remote_orders (id integer) SERVER foreign_server",
        "CREATE STATISTICS order_stats ON user_id, total FROM orders",
        "CREATE STATISTICS ON user_id, total FROM orders",
        'CREATE COLLATION copy_c FROM pg_catalog."C"',
        "CREATE SERVER foreign_server FOREIGN DATA WRAPPER postgres_fdw",
        "CREATE USER MAPPING FOR CURRENT_USER SERVER foreign_server",
        "CREATE TEMPORARY SEQUENCE scratch_ids",
        "CREATE UNLOGGED SEQUENCE scratch_ids",
    ],
)
def test_postgres_creation_native_guards(statement: str) -> None:
    findings = _check(f"{statement};")
    assert len(findings) == 1
    assert "IF NOT EXISTS" in findings[0].message


@pytest.mark.parametrize(
    ("object_kind", "target"),
    [
        ("EXTENSION", "pgcrypto"),
        ("SCHEMA", "billing"),
        ("SEQUENCE", "order_seq"),
        ("VIEW", "order_totals"),
        ("MATERIALIZED VIEW", "order_totals"),
        ("FOREIGN TABLE", "remote_orders"),
        ("FOREIGN DATA WRAPPER", "postgres_fdw"),
        ("TYPE", "point_3d"),
        ("DOMAIN", "positive_integer"),
        ("FUNCTION", "legacy_fn()"),
        ("PROCEDURE", "legacy_proc()"),
        ("ROUTINE", "legacy_routine()"),
        ("TRIGGER", "audit_orders ON orders"),
        ("EVENT TRIGGER", "ddl_audit"),
        ("POLICY", "tenant_policy ON orders"),
        ("RULE", "rewrite_orders ON orders"),
        ("COLLATION", "copy_c"),
        ("CONVERSION", "utf8_to_latin1"),
        ("STATISTICS", "order_stats"),
        ("SERVER", "foreign_server"),
        ("USER MAPPING", "FOR CURRENT_USER SERVER foreign_server"),
        ("ACCESS METHOD", "custom_method"),
        ("AGGREGATE", "custom_sum(integer)"),
        ("CAST", "(integer AS text)"),
        ("OPERATOR", "+ (integer, integer)"),
        ("OPERATOR CLASS", "custom_ops USING btree"),
        ("OPERATOR FAMILY", "custom_ops USING btree"),
        ("LANGUAGE", "plpython3u"),
        ("PROCEDURAL LANGUAGE", "plpython3u"),
        ("PUBLICATION", "order_changes"),
        ("SUBSCRIPTION", "order_changes"),
        ("TEXT SEARCH CONFIGURATION", "custom_search"),
        ("TEXT SEARCH DICTIONARY", "custom_search"),
        ("TEXT SEARCH PARSER", "custom_search"),
        ("TEXT SEARCH TEMPLATE", "custom_search"),
        ("TRANSFORM", "FOR integer LANGUAGE plpython3u"),
        ("ROLE", "legacy_reader"),
        ("GROUP", "legacy_reader"),
        ("USER", "legacy_reader"),
        ("DATABASE", "legacy_database"),
        ("TABLESPACE", "legacy_space"),
    ],
)
def test_postgres_drop_native_guards(object_kind: str, target: str) -> None:
    assert len(_check(f"DROP {object_kind} {target};")) == 1
    assert _check(f"DROP {object_kind} IF EXISTS {target};") == []


@pytest.mark.parametrize(
    ("action", "guarded"),
    [
        ("ADD note TEXT", "ADD IF NOT EXISTS note TEXT"),
        ('ADD "note" TEXT', 'ADD IF NOT EXISTS "note" TEXT'),
        ("DROP note", "DROP IF EXISTS note"),
        ('DROP "note"', 'DROP IF EXISTS "note"'),
        ("DROP COLUMN note", "DROP COLUMN IF EXISTS note"),
        ("DROP CONSTRAINT total_nonnegative", "DROP CONSTRAINT IF EXISTS total_nonnegative"),
        ("ALTER COLUMN id DROP IDENTITY", "ALTER COLUMN id DROP IDENTITY IF EXISTS"),
        ('ALTER "total" DROP EXPRESSION', 'ALTER "total" DROP EXPRESSION IF EXISTS'),
    ],
)
def test_alter_table_replay_guards(action: str, guarded: str) -> None:
    findings = _check(f'ALTER TABLE IF EXISTS ONLY "sales"."orders" {action};')
    assert len(findings) == 1
    assert _check(f'ALTER TABLE IF EXISTS ONLY "sales"."orders" {guarded};') == []


def test_composite_type_drop_attribute_has_native_guard() -> None:
    assert len(_check("ALTER TYPE point_3d DROP ATTRIBUTE z;")) == 1
    assert _check("ALTER TYPE point_3d DROP ATTRIBUTE IF EXISTS z;") == []


def test_multi_action_alter_ignores_nested_and_quoted_commas() -> None:
    source = """ALTER TABLE orders
    ADD CONSTRAINT valid_pair CHECK (greatest(a, b) >= 0),
    ADD "note,description" TEXT DEFAULT concat('x', ', ADD shadow'),
    DROP old_note,
    ALTER COLUMN total DROP DEFAULT;
"""
    findings = _check(source)
    assert [(finding.line, finding.col) for finding in findings] == [(3, 5), (4, 5)]


@pytest.mark.parametrize(
    "source",
    [
        "CREATE TYPE point_3d AS (x integer, y integer, z integer);",
        "CREATE DOMAIN positive_integer AS integer CHECK (VALUE > 0);",
        "CREATE VIEW order_totals AS SELECT 1 AS total;",
        "CREATE OR REPLACE VIEW order_totals AS SELECT 1 AS total;",
        "ALTER TABLE orders ADD CHECK (total >= 0);",
        "ALTER TABLE orders ADD UNIQUE (external_id);",
        "ALTER TABLE orders ADD PRIMARY KEY (id);",
        "ALTER TABLE orders ADD FOREIGN KEY (user_id) REFERENCES users (id);",
        "ALTER TABLE orders ALTER COLUMN total SET DEFAULT 0;",
        "ALTER TABLE orders ALTER COLUMN total DROP DEFAULT;",
        "ALTER TABLE orders ALTER COLUMN total DROP NOT NULL;",
        "ALTER TABLE orders RENAME COLUMN note TO description;",
        "DROP OWNED BY legacy_owner;",
        "SELECT \"DROP VIEW missing\", 'DROP SEQUENCE missing';",
        "SELECT $data$DROP DOMAIN missing; ALTER TABLE orders ADD shadow TEXT;$data$;",
        "/* DROP EXTENSION pgcrypto; */ -- ALTER TABLE orders ADD shadow TEXT",
    ],
)
def test_unsupported_forms_and_sql_data_remain_out_of_scope(source: str) -> None:
    assert _check(source) == []


def test_comments_between_guard_tokens_do_not_create_false_positives() -> None:
    source = """CREATE MATERIALIZED VIEW /* explanation */ IF NOT EXISTS totals AS SELECT 1 AS total;
DROP USER MAPPING /* explanation */ IF EXISTS FOR CURRENT_USER SERVER foreign_server;
ALTER TABLE orders ADD /* explanation */ IF NOT EXISTS note TEXT,
    DROP /* explanation */ IF EXISTS old_note;
"""
    assert _check(source) == []


@pytest.mark.parametrize("dialect", ["mysql", "sqlite"])
def test_postgres_only_guards_do_not_leak_to_other_dialects(dialect: str) -> None:
    source = """DROP TRIGGER legacy_trigger;
ALTER TABLE orders DROP COLUMN note;
ALTER TABLE orders ADD note TEXT;
"""
    assert _check(f"-- dialect: {dialect}\n{source}") == []


@pytest.mark.parametrize(
    ("source", "guarded"),
    [
        (
            "CREATE MATERIALIZED VIEW totals AS SELECT 1 AS total;",
            "CREATE MATERIALIZED VIEW IF NOT EXISTS totals AS SELECT 1 AS total;",
        ),
        ("CREATE TEMP SEQUENCE scratch_ids;", "CREATE TEMP SEQUENCE IF NOT EXISTS scratch_ids;"),
        ("DROP VIEW order_totals;", "DROP VIEW IF EXISTS order_totals;"),
        ("DROP TYPE point_3d;", "DROP TYPE IF EXISTS point_3d;"),
        ("DROP SEQUENCE order_seq;", "DROP SEQUENCE IF EXISTS order_seq;"),
        (
            "ALTER TABLE orders DROP CONSTRAINT total_nonnegative;",
            "ALTER TABLE orders DROP CONSTRAINT IF EXISTS total_nonnegative;",
        ),
        ("ALTER TABLE orders DROP COLUMN note;", "ALTER TABLE orders DROP COLUMN IF EXISTS note;"),
    ],
)
def test_expanded_safe_fixes_converge(source: str, guarded: str) -> None:
    path = Path("db/migrations/001.sql")
    assert fix_source(path, source, rule_ids=["idempotent-ddl"]) == guarded
    assert fix_source(path, guarded, rule_ids=["idempotent-ddl"]) == guarded
    assert _check(guarded) == []


@pytest.mark.parametrize(
    "source",
    [
        "CREATE STATISTICS ON user_id, total FROM orders;",
        "CREATE STATISTICS order_stats ON user_id, total FROM orders;",
        "DROP EXTENSION pgcrypto;",
        "ALTER TABLE orders ADD note TEXT;",
        "ALTER TABLE orders DROP note;",
        "ALTER TABLE orders ALTER COLUMN id DROP IDENTITY;",
    ],
)
def test_diagnostics_without_a_proven_safe_fix_preserve_source(source: str) -> None:
    assert len(_check(source)) == 1
    assert fix_source(Path("db/migrations/001.sql"), source, rule_ids=["idempotent-ddl"]) == source


def test_copy_input_cannot_become_executable_ddl() -> None:
    signal = "ALTER TABLE orders ADD note TEXT; DROP VIEW order_totals;"
    source = f"COPY seed(body) FROM STDIN;\n{signal}\n\\.\n{signal}"
    assert _check(source) == []
    prefix = "DROP SEQUENCE order_seq;\n"
    assert _check(f"{prefix}{source}") == _check(prefix)


@pytest.mark.parametrize(
    "prefix",
    [
        "COPY seed TO STDOUT;",
        "SELECT 'COPY seed FROM STDIN;';",
        "DO $$ BEGIN RAISE NOTICE 'COPY seed FROM STDIN;'; END $$;",
    ],
)
def test_copy_near_misses_preserve_later_guard_findings(prefix: str) -> None:
    assert len(_check(f"{prefix}\nALTER TABLE orders ADD note TEXT;")) == 1


@pytest.mark.parametrize(
    "source",
    [
        "SELECT x$DROP VIEW FROM docs;",
        "SELECT x\u0301DROP DOMAIN FROM docs;",
        "SELECT x$CREATE INDEX FROM docs;",
        "SELECT x\u0301ADD COLUMN FROM docs;",
        "SELECT CREATE İNDEX FROM docs;",
    ],
)
def test_identifier_fragments_do_not_become_ddl_keywords(source: str) -> None:
    assert _check(source) == []
