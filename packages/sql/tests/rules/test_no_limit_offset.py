from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.no_limit_offset import NoLimitOffset


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return NoLimitOffset().check(Path("query.sql"), source)


def test_flags_offset():
    src = "SELECT * FROM call ORDER BY id LIMIT 50 OFFSET 100;"
    diags = _check(src)
    assert len(diags) == 1
    assert "cursor" in diags[0].message


def test_is_case_insensitive():
    src = "select * from call order by id limit 50 offset 100;"
    assert len(_check(src)) == 1


def test_allows_cursor_pagination():
    src = "SELECT * FROM call WHERE id > :cursor ORDER BY id LIMIT 50;"
    assert _check(src) == []


def test_allows_offset_substring_identifiers():
    src = "SELECT utc_offset, byte_offset_end FROM tz_info"
    assert _check(src) == []


def test_allows_quoted_offset_identifier():
    src = 'SELECT "offset" FROM tz_info ORDER BY id'
    assert _check(src) == []


def test_skips_comment_lines():
    src = """
-- OFFSET is forbidden, use cursor pagination
/* LIMIT 10 OFFSET 20 */
SELECT * FROM call WHERE id > :cursor ORDER BY id LIMIT 50;
"""
    assert _check(src) == []


def test_skips_offset_inside_string_literal():
    src = "INSERT INTO doc (body) VALUES ('use OFFSET sparingly');"
    assert _check(src) == []


# --------------------------------------------------------------------------- #
# Cross-package parity with SARJ025 and the TS twin                            #
# (`packages/python/.../no_offset_pagination.py`,                              #
#  `packages/typescript/src/rules/no-offset-pagination.ts`).                   #
# All three flag `OFFSET` only when a value/param token follows, and all three #
# share ONE parameter alternation. This rule used to be a bare `\bOFFSET\b`,   #
# so identical SQL was clean in `.py` and a finding in `.sql`.                 #
# --------------------------------------------------------------------------- #

PARAM_MARKERS = {
    "pyformat": "SELECT id FROM t ORDER BY id LIMIT %s OFFSET %s;",
    "pyformat_named": "SELECT id FROM t ORDER BY id LIMIT %(n)s OFFSET %(off)s;",
    "qmark": "SELECT id FROM t ORDER BY id LIMIT ? OFFSET ?;",
    "numbered_qmark": "SELECT id FROM t ORDER BY id LIMIT ?1 OFFSET ?2;",
    "named_colon": "SELECT id FROM t ORDER BY id LIMIT :n OFFSET :off;",
    "named_at": "SELECT id FROM t ORDER BY id LIMIT @n OFFSET @off;",
    "numeric_dollar": "SELECT id FROM t ORDER BY id LIMIT $1 OFFSET $2;",
    "bare_digit": "SELECT id FROM t ORDER BY id LIMIT 10 OFFSET 20;",
}


@pytest.mark.parametrize("source", PARAM_MARKERS.values(), ids=list(PARAM_MARKERS))
def test_every_shared_param_marker_is_detected(source: str):
    assert len(_check(source)) == 1


NON_PAGINATION = {
    "add_column_named_offset": (
        "ALTER TABLE batch ADD COLUMN offset INTEGER NOT NULL DEFAULT 0;"
    ),
    "create_table_column_named_offset": "CREATE TABLE t (id BIGINT, offset INTEGER);",
    "bigquery_with_offset": "SELECT x, i FROM UNNEST(arr) AS x WITH OFFSET AS i;",
}


@pytest.mark.parametrize("source", NON_PAGINATION.values(), ids=list(NON_PAGINATION))
def test_offset_without_a_value_token_is_not_pagination(source: str):
    """A migration adding an `offset` column used to be told to use cursor pagination."""
    assert _check(source) == []
