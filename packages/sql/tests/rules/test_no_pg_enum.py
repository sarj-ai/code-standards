from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sarj_sql_lint.rules.no_pg_enum import NoPgEnum


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return NoPgEnum().check(Path("migration.sql"), source)


def test_flags_create_type_as_enum():
    src = "CREATE TYPE call_status AS ENUM ('pending', 'active', 'completed');"
    diags = _check(src)
    assert len(diags) == 1
    assert "TEXT + CHECK" in diags[0].message


def test_flags_multiline_create_type_as_enum():
    src = """
CREATE TYPE call_status
    AS ENUM ('pending', 'active', 'completed');
"""
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2


def test_flags_alter_type_add_value():
    src = "ALTER TYPE call_status ADD VALUE 'archived';"
    assert len(_check(src)) == 1


def test_is_case_insensitive():
    src = "create type call_status as enum ('pending', 'active');"
    assert len(_check(src)) == 1


def test_allows_text_with_check_constraint():
    src = """
CREATE TABLE IF NOT EXISTS call (
    status TEXT NOT NULL CHECK (status IN ('pending', 'active', 'completed'))
);
"""
    assert _check(src) == []


def test_allows_create_type_composite():
    src = "CREATE TYPE point_2d AS (x DOUBLE PRECISION, y DOUBLE PRECISION);"
    assert _check(src) == []


def test_skips_comment_lines():
    src = """
-- CREATE TYPE call_status AS ENUM is forbidden; see SARJ103
/* CREATE TYPE x AS ENUM ('a') */
"""
    assert _check(src) == []


def test_skips_enum_word_inside_string_literal():
    src = "INSERT INTO doc (body) VALUES ('CREATE TYPE x AS ENUM (a)');"
    assert _check(src) == []
