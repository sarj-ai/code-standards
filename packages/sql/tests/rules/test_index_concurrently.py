from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.index_concurrently import IndexConcurrently


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return IndexConcurrently().check(Path("migration.sql"), source)


_PUBLIC_EXAMPLES = IndexConcurrently.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(IndexConcurrently().check(Path(focus.path), focus.source)) == example.expected_count


def test_flags_create_index_without_concurrently():
    src = "CREATE INDEX idx_orders_user ON orders(user_id);"
    diags = _check(src)
    assert len(diags) == 1
    assert "CONCURRENTLY" in diags[0].message


def test_flags_unnamed_index_on_existing_table():
    source = "-- dialect: postgres\nCREATE INDEX ON users(email);"
    assert len(_check(source)) == 1


def test_dbmate_transactional_migration_gets_compatible_paired_guidance() -> None:
    source = "-- migrate:up\nSET LOCAL lock_timeout = '2s';\nCREATE INDEX idx ON users(email);\n"

    (finding,) = _check(source)

    assert "transaction:false" in finding.message
    assert "SET`/`RESET" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        "SELECT '-- migrate:up';\nCREATE INDEX idx ON users(email);\n",
        "-- documentation mentions -- migrate:up\nCREATE INDEX idx ON users(email);\n",
        "DO $body$\n-- migrate:up\n$body$;\nCREATE INDEX idx ON users(email);\n",
    ],
)
def test_dbmate_guidance_requires_an_exact_live_directive(source: str) -> None:
    (finding,) = _check(source)
    assert "dbmate" not in finding.message


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


@pytest.mark.parametrize(
    ("created", "indexed", "expected"),
    [
        pytest.param("scratch.items", "app.items", 1, id="different-schemas"),
        pytest.param('"App".items', "app.items", 1, id="quoted-schema-case"),
        pytest.param('"Items"', "items", 1, id="quoted-table-case"),
        pytest.param('"app.items"', "app.items", 1, id="quoted-dot-is-not-qualification"),
        pytest.param("café", "caf", 1, id="unicode-name-does-not-prove-prefix"),
        pytest.param("café", "café", 0, id="same-unquoted-unicode"),
        pytest.param("CAFÉ", "cafÉ", 0, id="unicode-folds-ascii-only"),
        pytest.param("CAFÉ", "café", 1, id="unicode-case-remains-distinct"),
        pytest.param('"cafÉ"', "CAFÉ", 0, id="quoted-unicode-equivalent"),
        pytest.param('"CAFÉ"', "CAFÉ", 1, id="quoted-unicode-preserves-ascii-case"),
        pytest.param('"नमस्ते"', "नमस्ते", 0, id="unicode-combining-characters"),
        pytest.param('"item\nname"', '"item\nname"', 0, id="quoted-newline"),
        pytest.param("app /* explanation */ . items", "app", 1, id="comment-does-not-truncate-qualification"),
        pytest.param("public.items", "items", 0, id="qualified-create-may-be-unqualified-target"),
        pytest.param("items", "public.items", 0, id="unqualified-create-may-be-qualified-target"),
        pytest.param("current_db.public.items", "public.items", 0, id="catalog-qualified-create"),
        pytest.param("public.items", "current_db.public.items", 0, id="catalog-qualified-target"),
        pytest.param('"current.db".public.items', "public.items", 0, id="quoted-catalog"),
        pytest.param("current_db.scratch.items", "current_db.app.items", 1, id="catalog-distinct-schemas"),
        pytest.param("current_db.scratch.items", "app.items", 1, id="catalog-create-distinct-schema"),
        pytest.param("scratch.items", "current_db.app.items", 1, id="catalog-target-distinct-schema"),
        pytest.param('current_db."App".items', "app.items", 1, id="catalog-preserves-quoted-schema"),
        pytest.param("pg_temp.items", "pg_temp_3.items", 0, id="temp-alias-create"),
        pytest.param("pg_temp_3.items", "pg_temp.items", 0, id="temp-alias-target"),
        pytest.param('"pg_temp_3".items', "pg_temp.items", 0, id="quoted-numbered-temp-schema"),
        pytest.param("current_db.pg_temp_3.items", "pg_temp.items", 0, id="catalog-temp-create"),
        pytest.param("pg_temp_3.items", "current_db.pg_temp.items", 0, id="catalog-temp-target"),
        pytest.param("public.items", "pg_temp_3.items", 0, id="explicit-temp-target-is-session-local"),
        pytest.param("pg_temp_3.items", "public.items", 1, id="temp-and-ordinary-schemas-differ"),
        pytest.param("pg_temp.items", "pg_temp_custom.items", 1, id="temp-like-schema-is-not-numbered"),
        pytest.param("pg_temp.items", '"PG_TEMP_3".items', 1, id="quoted-uppercase-temp-like-schema"),
        pytest.param("APP.ITEMS", "app.items", 0, id="unquoted-case-folds"),
        pytest.param('"app"."items"', "app.items", 0, id="quoted-lowercase-equivalent"),
        pytest.param("app . items", "app.items", 0, id="qualification-whitespace"),
        pytest.param("app /* explanation */ . items", "app.items", 0, id="qualification-comments"),
        pytest.param('"App"."Items"', '"App"."Items"', 0, id="same-quoted-case"),
        pytest.param('"ap""p"."it""ems"', '"ap""p"."it""ems"', 0, id="escaped-identifier-quotes"),
        pytest.param('"app data"."item data"', '"app data"."item data"', 0, id="quoted-identifier-spaces"),
        pytest.param("app.it$ems", "app.it$ems", 0, id="dollar-in-unquoted-identifier"),
    ],
)
def test_new_table_exemption_preserves_postgres_relation_identity(created: str, indexed: str, expected: int) -> None:
    source = (
        f"CREATE TABLE IF NOT EXISTS {created} (id bigint);\nCREATE INDEX IF NOT EXISTS items_idx ON {indexed}(id);\n"
    )

    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        pytest.param("pg_temp.items", 0, id="current-temp-alias"),
        pytest.param("pg_temp_3.items", 0, id="numbered-temp-schema"),
        pytest.param('"pg_temp".items', 0, id="quoted-temp-alias"),
        pytest.param("current_db.pg_temp.items", 0, id="catalog-temp-target"),
        pytest.param('"PG_TEMP".items', 1, id="uppercase-schema-is-distinct"),
        pytest.param('"PG_TEMP_3".items', 1, id="uppercase-numbered-schema-is-distinct"),
        pytest.param("pg_temp_custom.items", 1, id="temp-like-name-is-ordinary"),
        pytest.param('"pg_temp.items"', 1, id="quoted-dot-is-an-ordinary-table-name"),
        pytest.param("public.items", 1, id="ordinary-table-still-requires-concurrency"),
    ],
)
def test_explicit_temporary_targets_need_no_same_file_creation_proof(target: str, expected: int) -> None:
    source = f"CREATE TABLE scratch.items(id int);\nCREATE INDEX items_idx ON {target}(id);\n"

    assert len(_check(source)) == expected


@pytest.mark.parametrize("search_path", ["public", "another_schema"])
def test_search_path_does_not_override_ambiguous_qualification_abstention(search_path: str) -> None:
    source = (
        f"SET search_path={search_path};\nCREATE TABLE public.items(id int);\nCREATE INDEX items_idx ON items(id);\n"
    )

    assert _check(source) == []


def test_on_inside_a_quoted_index_name_does_not_replace_the_real_target() -> None:
    source = 'CREATE TABLE items(id int);\nCREATE INDEX IF NOT EXISTS "name ON unrelated" ON items(id);\n'

    assert _check(source) == []


@pytest.mark.parametrize(("target", "expected"), [("existing", 1), ('"on"', 0)])
def test_on_inside_an_unquoted_unicode_index_name_is_not_a_keyword(target: str, expected: int) -> None:
    source = f'CREATE TABLE "on"(id int);\nCREATE INDEX name_🐈ON ON {target}(id);\n'

    assert len(_check(source)) == expected


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
    src = """
CREATE INDEX idx_orders_user ON orders (user_id);
CREATE TABLE orders (id BIGSERIAL PRIMARY KEY, user_id BIGINT);
"""
    assert len(_check(src)) == 1


def test_flags_index_when_only_a_commented_out_create_table_precedes_it():
    src = """
-- CREATE TABLE orders (id BIGSERIAL PRIMARY KEY);
CREATE INDEX idx_orders_user ON orders (user_id);
"""
    assert len(_check(src)) == 1


def test_allows_plain_create_index_in_sqlite():
    src = "CREATE INDEX `i` ON `users` (`email`);"
    assert _check(src) == []


def test_allows_plain_create_index_in_mysql():
    src = """
CREATE TABLE `users` (`id` int UNSIGNED NOT NULL AUTO_INCREMENT) ENGINE=InnoDB;
CREATE INDEX `email_idx` ON `sessions` (`email`);
"""
    assert _check(src) == []


def test_flags_plain_create_index_with_no_dialect_marker():
    src = 'CREATE INDEX idx_users_email ON "users" (email);'
    assert len(_check(src)) == 1


def test_reports_each_blocking_index_build() -> None:
    source = 'CREATE INDEX idx_users_email ON "users" (email);\nCREATE INDEX idx_users_name ON "users" (name);\n'

    assert [finding.line for finding in _check(source)] == [1, 2]


def test_each_dbmate_section_gets_its_own_native_transaction_guidance() -> None:
    source = "-- migrate:up transaction:false\nCREATE INDEX first_idx ON public_example(first);\n-- migrate:down transaction:true\nCREATE INDEX second_idx ON public_example(second);\n"
    first, second = _check(source)
    assert "transaction:false" not in first.message
    assert "transaction:false" in second.message
