from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.prefer_uuidv7_default import PreferUuidv7Default


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return PreferUuidv7Default().check(Path("migration.sql"), source)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "CREATE TABLE IF NOT EXISTS call (id UUID PRIMARY KEY DEFAULT gen_random_uuid());",
            id="create-table-default",
        ),
        pytest.param(
            "ALTER TABLE call ALTER COLUMN id SET DEFAULT gen_random_uuid();",
            id="alter-column-default",
        ),
        pytest.param(
            "INSERT INTO call (id) VALUES (gen_random_uuid()) ON CONFLICT DO NOTHING;",
            id="insert-values",
        ),
        pytest.param("SELECT GEN_RANDOM_UUID();", id="uppercase"),
        pytest.param("SELECT gen_random_uuid ();", id="space-before-paren"),
    ],
)
def test_flags_gen_random_uuid(source: str):
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ109"
    assert "uuidv7()" in diags[0].message


def test_reports_each_occurrence():
    src = "CREATE TABLE t (\n  a UUID DEFAULT gen_random_uuid(),\n  b UUID DEFAULT gen_random_uuid()\n);"
    assert [d.line for d in _check(src)] == [2, 3]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("CREATE TABLE t (id UUID PRIMARY KEY DEFAULT uuidv7());", id="already-uuidv7"),
        pytest.param("-- was DEFAULT gen_random_uuid()\nSELECT 1;", id="line-comment"),
        pytest.param("/* DEFAULT gen_random_uuid() */\nSELECT 1;", id="block-comment"),
        pytest.param("INSERT INTO note (body) VALUES ('gen_random_uuid()');", id="quoted-value"),
        pytest.param('SELECT "gen_random_uuid()" FROM t;', id="quoted-identifier"),
        pytest.param("SELECT gen_random_uuid_v7();", id="different-identifier"),
    ],
)
def test_allows(source: str):
    assert _check(source) == []


def test_dollar_quoted_body_is_masked():
    src = "CREATE FUNCTION f() RETURNS text AS $$ SELECT 'gen_random_uuid()' $$ LANGUAGE sql;"
    assert _check(src) == []


def test_column_is_one_based():
    assert _check("SELECT gen_random_uuid();")[0].col == 8
