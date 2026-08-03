from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sarj_sql_lint.rules.index_concurrently import IndexConcurrently


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return IndexConcurrently().check(Path("migration.sql"), source)


def test_flags_create_index_without_concurrently():
    src = "CREATE INDEX idx_orders_user ON orders(user_id);"
    diags = _check(src)
    assert len(diags) == 1
    assert "CONCURRENTLY" in diags[0].message


def test_flags_create_unique_index_without_concurrently():
    src = "CREATE UNIQUE INDEX idx_orders_user ON orders(user_id);"
    assert len(_check(src)) == 1


def test_flags_create_index_if_not_exists_without_concurrently():
    src = "CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);"
    assert len(_check(src)) == 1


def test_allows_create_index_concurrently():
    src = "CREATE INDEX CONCURRENTLY idx_orders_user ON orders(user_id);"
    assert _check(src) == []


def test_allows_create_unique_index_concurrently_if_not_exists():
    src = "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_u ON orders(user_id);"
    assert _check(src) == []


def test_is_case_insensitive():
    src = "create index idx_orders_user on orders(user_id);"
    assert len(_check(src)) == 1


def test_ignores_drop_index():
    src = "DROP INDEX CONCURRENTLY IF EXISTS idx_orders_user;"
    assert _check(src) == []


def test_skips_comment_lines():
    src = """
-- CREATE INDEX idx ON orders(user_id);
/* CREATE INDEX idx2 ON orders(note); */
"""
    assert _check(src) == []


# Test creating index on a table created in the same file.


def test_allows_index_on_table_created_in_the_same_file():
    src = """
CREATE TABLE orders (id BIGSERIAL PRIMARY KEY, user_id BIGINT);
CREATE INDEX idx_orders_user ON orders (user_id);
"""
    assert _check(src) == []


def test_allows_index_on_quoted_table_created_in_the_same_file():
    src = """
CREATE TABLE "Workflow" ("id" TEXT NOT NULL, "userId" INTEGER);
CREATE INDEX "Workflow_userId_idx" ON "Workflow"("userId");
"""
    assert _check(src) == []


def test_allows_index_on_schema_qualified_table_created_in_the_same_file():
    src = """
CREATE TABLE IF NOT EXISTS public.orders (id BIGSERIAL PRIMARY KEY, user_id BIGINT);
CREATE INDEX idx_orders_user ON public.orders (user_id);
"""
    assert _check(src) == []


def test_allows_index_whose_on_clause_is_on_a_later_line():
    src = """
CREATE TABLE orders (id BIGSERIAL PRIMARY KEY, user_id BIGINT);
CREATE INDEX idx_orders_user
    ON orders (user_id);
"""
    assert _check(src) == []


def test_flags_index_on_a_table_not_created_in_this_file():
    src = """
CREATE TABLE orders (id BIGSERIAL PRIMARY KEY);
CREATE INDEX idx_users_email ON users (email);
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3


def test_flags_index_created_before_its_table_in_the_same_file():
    """The boundary: "earlier in the file" is ordered, not merely "present"."""
    src = """
CREATE INDEX idx_orders_user ON orders (user_id);
CREATE TABLE orders (id BIGSERIAL PRIMARY KEY, user_id BIGINT);
"""
    assert len(_check(src)) == 1


def test_flags_index_when_only_a_commented_out_create_table_precedes_it():
    """The boundary: a masked `CREATE TABLE` is not a `CREATE TABLE`."""
    src = """
-- CREATE TABLE orders (id BIGSERIAL PRIMARY KEY);
CREATE INDEX idx_orders_user ON orders (user_id);
"""
    assert len(_check(src)) == 1


# Dialect tests.


def test_allows_plain_create_index_in_sqlite():
    """CONCURRENTLY is a syntax error outside Postgres."""
    src = "CREATE INDEX `i` ON `users` (`email`);"
    assert _check(src) == []


def test_allows_plain_create_index_in_mysql():
    src = """
CREATE TABLE `users` (`id` int UNSIGNED NOT NULL AUTO_INCREMENT) ENGINE=InnoDB;
CREATE INDEX `email_idx` ON `sessions` (`email`);
"""
    assert _check(src) == []


def test_flags_plain_create_index_with_no_dialect_marker():
    """The boundary: the dialect guard must not widen to unmarked Postgres SQL."""
    src = 'CREATE INDEX idx_users_email ON "users" (email);'
    assert len(_check(src)) == 1
