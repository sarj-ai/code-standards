from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.prefer_text_over_varchar import PreferTextOverVarchar


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return PreferTextOverVarchar().check(Path("migration.sql"), source)


_PUBLIC_EXAMPLES = PreferTextOverVarchar.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferTextOverVarchar().check(Path(focus.path), focus.source)) == example.expected_count


def test_flags_varchar_with_length():
    src = "CREATE TABLE IF NOT EXISTS u (name VARCHAR(255) NOT NULL);"
    diags = _check(src)
    assert len(diags) == 1
    assert "TEXT" in diags[0].message


def test_flags_character_varying_with_length():
    src = "ALTER TABLE u ADD COLUMN IF NOT EXISTS bio CHARACTER VARYING(1024);"
    assert len(_check(src)) == 1


def test_is_case_insensitive_and_tolerates_spacing():
    src = "name varchar (64) not null"
    assert len(_check(src)) == 1


def test_flags_each_occurrence():
    src = """
CREATE TABLE IF NOT EXISTS u (
    first_name VARCHAR(50),
    last_name VARCHAR(50)
);
"""
    assert len(_check(src)) == 2


def test_allows_text():
    src = """
CREATE TABLE IF NOT EXISTS u (
    name TEXT NOT NULL CHECK (char_length(name) <= 255)
);
"""
    assert _check(src) == []


def test_allows_bare_varchar_identifier_substrings():
    src = "SELECT my_varchar(255) FROM helper_functions"
    assert _check(src) == []


def test_skips_comment_lines():
    src = """
-- VARCHAR(255) is forbidden; use TEXT
/* CHARACTER VARYING(10) too */
"""
    assert _check(src) == []


def test_skips_trailing_inline_comment():
    src = "name TEXT NOT NULL -- was VARCHAR(255)"
    assert _check(src) == []


def test_skips_varchar_inside_string_literal():
    src = "INSERT INTO doc (body) VALUES ('column type VARCHAR(255)');"
    assert _check(src) == []


def test_allows_varchar_in_mysql():
    src = """
CREATE TABLE `deployments` (
  `id` varchar(256) NOT NULL,
  `runtime` varchar(256) NOT NULL DEFAULT 'node'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""
    assert _check(src) == []


def test_allows_varchar_in_sqlite():
    src = "CREATE TABLE `t` (`name` varchar(64) NOT NULL, `id` integer AUTOINCREMENT);"
    assert _check(src) == []


def test_flags_varchar_with_no_dialect_marker():
    src = 'CREATE TABLE "users" (email VARCHAR(255) NOT NULL);'
    assert len(_check(src)) == 1


def test_allows_varchar_in_a_pg_dump_snapshot():
    src = """
-- PostgreSQL database dump
-- Dumped by pg_dump version 16.2
CREATE TABLE public.users (email character varying(255));
"""
    assert PreferTextOverVarchar().check(Path("migration.sql"), src) == []


def test_generated_migration_is_redirected_not_silenced(tmp_path: Path) -> None:
    root = tmp_path / "prisma" / "migrations"
    (root / "20240101000000_init").mkdir(parents=True)
    (root / "migration_lock.toml").write_text('provider = "postgresql"\n')
    migration = root / "20240101000000_init" / "migration.sql"
    src = 'CREATE TABLE "User" ("email" VARCHAR(255) NOT NULL);'
    migration.write_text(src)

    diags = PreferTextOverVarchar().check(migration, src)
    assert len(diags) == 1
    assert "schema.prisma" in diags[0].message
