from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.no_offset_pagination import NoOffsetPagination


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "queries/events.sql") -> list[Diagnostic]:
    return NoOffsetPagination().check(Path(path), source)


_PUBLIC_EXAMPLES = NoOffsetPagination.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoOffsetPagination().check(Path(focus.path), focus.source)) == example.expected_count


PARAM_MARKERS = {
    "pyformat": "SELECT id FROM event ORDER BY id LIMIT 50 OFFSET %s;",
    "pyformat-named": "SELECT id FROM event ORDER BY id LIMIT 50 OFFSET %(offset)s;",
    "qmark": "SELECT id FROM event ORDER BY id LIMIT 50 OFFSET ?;",
    "numbered-qmark": "SELECT id FROM event ORDER BY id LIMIT 50 OFFSET ?2;",
    "named-colon": "SELECT id FROM event ORDER BY id LIMIT 50 OFFSET :offset;",
    "named-at": "SELECT id FROM event ORDER BY id LIMIT 50 OFFSET @offset;",
    "numeric-dollar": "SELECT id FROM event ORDER BY id LIMIT 50 OFFSET $2;",
}


@pytest.mark.parametrize("source", PARAM_MARKERS.values(), ids=PARAM_MARKERS)
def test_flags_every_dynamic_offset_marker(source: str) -> None:
    findings = _check(source)

    assert len(findings) == 1
    assert "stable, unique cursor" in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        "SELECT id FROM event\nORDER BY id\nLIMIT :limit\nOFFSET\n:offset;",
        "SELECT id FROM event\r\nORDER BY id\r\nOFFSET\r\n:offset ROWS\r\nFETCH NEXT :limit ROWS ONLY;",
        "SELECT id FROM event ORDER BY id OFFSET (:offset);",
        "SELECT id FROM event ORDER BY id OFFSET (:page * :limit);",
        "SELECT id FROM event ORDER BY id OFFSET CAST(:offset AS integer) ROWS;",
        "SELECT id FROM event ORDER BY id OFFSET COALESCE(:offset, 0);",
        "SELECT id FROM event ORDER BY id OFFSET +:offset;",
        "SELECT id FROM event ORDER BY id OFFSET :offset::integer;",
        "SELECT id FROM event ORDER BY id OFFSET (:offset)::integer;",
        "SELECT id FROM event ORDER BY id OFFSET $1::pg_catalog.int8[] ROWS;",
        "SELECT id FROM event ORDER BY id OFFSET ((:offset));",
        "SELECT * FROM (SELECT id FROM event OFFSET :offset) AS page;",
        "WITH visible AS (SELECT id FROM event WHERE active) SELECT id FROM visible OFFSET :offset;",
        "SELECT id FROM event LIMIT :offset, :limit;",
        "SELECT id FROM event LIMIT ?, ?;",
        "SELECT id FROM event LIMIT $1, $2;",
        "SELECT id FROM event LIMIT :offset, 50;",
        "SELECT id FROM event OFFSET :offset;",
        "SELECT payload #>> '{items,0}' FROM event OFFSET :offset;",
    ],
    ids=(
        "multiline",
        "crlf-standard-fetch",
        "parenthesized",
        "parenthesized-expression",
        "cast-expression",
        "coalesce-expression",
        "unary-expression",
        "postfix-cast",
        "parenthesized-postfix-cast",
        "qualified-array-postfix-cast",
        "nested-parentheses",
        "subquery-closing-parenthesis",
        "cte",
        "mysql-dynamic-count",
        "mysql-qmark",
        "mysql-dollar",
        "mysql-literal-count",
        "no-order-by",
        "postgres-json-operator",
    ),
)
def test_flags_supported_dynamic_pagination_shapes(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "SELECT id FROM event ORDER BY id LIMIT 50 OFFSET 0;",
        "SELECT id FROM event ORDER BY id LIMIT 50 OFFSET 1;",
        "SELECT id FROM event ORDER BY id LIMIT 50 OFFSET 10;",
        "SELECT id FROM event ORDER BY id LIMIT 50 OFFSET 100;",
        "SELECT id FROM event ORDER BY id LIMIT 50 OFFSET 1000;",
    ],
    ids=("zero", "one", "ten", "hundred", "thousand"),
)
def test_preserves_fixed_ordinal_offsets(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        "SELECT utc_offset, byte_offset_end FROM tz_info;",
        'SELECT "OFFSET :offset" FROM tz_info;',
        "SELECT `OFFSET :offset` FROM tz_info;",
        "SELECT [OFFSET :offset] FROM tz_info;",
        "SELECT 'OFFSET :offset' FROM tz_info;",
        "SELECT id FROM event -- OFFSET :offset\nORDER BY id;",
        "SELECT id FROM event /* OFFSET :offset */ ORDER BY id;",
        "SELECT id FROM event # OFFSET :offset",
        "-- dialect: mysql\nSELECT id FROM event # OFFSET :offset",
        "SELECT x, i FROM UNNEST(arr) AS x WITH OFFSET AS i;",
        "INSERT INTO doc (body) VALUES ($$SELECT id FROM event OFFSET :offset$$);",
        "CREATE FUNCTION page() RETURNS void AS $$ SELECT id FROM event OFFSET :offset; $$ LANGUAGE SQL;",
        "ALTER TABLE event ADD COLUMN offset integer;",
        "SET application_name = OFFSET :offset;",
        "OFFSET :offset;",
        "SELECT id FROM event OFFSET;",
        "SELECT id FROM event FETCH NEXT :limit ROWS ONLY;",
        "SELECT id FROM event OFFSET {{ offset }};",
        "SELECT id FROM event OFFSET page_offset;",
        "SELECT id FROM event OFFSET %status;",
        "SELECT id FROM event OFFSET ?cursor;",
        "SELECT id FROM event OFFSET $2cursor;",
        "SELECT id FROM event OFFSET (:offset;",
        "SELECT id FROM event OFFSET CAST(:offset AS integer;",
        "SELECT fn(id FROM event OFFSET :offset;",
        "SELECT OFFSET :offset AS value FROM event;",
    ],
    ids=(
        "substring-identifiers",
        "quoted-identifier",
        "backtick-identifier",
        "bracket-identifier",
        "string",
        "line-comment",
        "block-comment",
        "mysql-hash-comment",
        "declared-mysql-hash-comment",
        "bigquery-with-offset",
        "dollar-quoted-data",
        "dollar-quoted-function-body",
        "ddl",
        "non-select-set",
        "fragment",
        "missing-expression",
        "fetch-without-offset",
        "template-expression",
        "bare-variable",
        "marker-prefix-percent",
        "marker-prefix-qmark",
        "marker-prefix-dollar",
        "unclosed-parenthesis",
        "unclosed-cast",
        "unbalanced-statement",
        "offset-before-from",
    ),
)
def test_preserves_nonpagination_or_ambiguous_sql(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("db/migrations/001.sql", "SELECT id FROM event ORDER BY id OFFSET :offset;"),
        ("db/migration/V1__events.sql", "SELECT id FROM event ORDER BY id OFFSET :offset;"),
        ("tests/queries/events.sql", "SELECT id FROM event ORDER BY id OFFSET :offset;"),
        ("__tests__/queries/events.sql", "SELECT id FROM event ORDER BY id OFFSET :offset;"),
        ("__mocks__/queries/events.sql", "SELECT id FROM event ORDER BY id OFFSET :offset;"),
        ("fixtures/queries/events.sql", "SELECT id FROM event ORDER BY id OFFSET :offset;"),
        ("snapshots/queries/events.sql", "SELECT id FROM event ORDER BY id OFFSET :offset;"),
        ("schema.sql", "-- PostgreSQL database dump\nSELECT id FROM event ORDER BY id OFFSET :offset;"),
        ("drizzle/0001.sql", "--> statement-breakpoint\nSELECT id FROM event ORDER BY id OFFSET :offset;"),
        ("generated/queries/events.sql", "SELECT id FROM event ORDER BY id OFFSET :offset;"),
        ("queries/events.generated.sql", "-- @generated\nSELECT id FROM event ORDER BY id OFFSET :offset;"),
    ],
    ids=(
        "migrations",
        "flyway",
        "tests",
        "dunder-tests",
        "dunder-mocks",
        "fixtures",
        "snapshots",
        "dump",
        "drizzle",
        "generated",
        "generated-file",
    ),
)
def test_excludes_nonproduction_sql(path: str, source: str) -> None:
    assert _check(source, path) == []


def test_reports_exact_multiline_clause_location() -> None:
    source = "SELECT id\nFROM event\nORDER BY id\nOFFSET (:offset);"

    finding = _check(source)[0]

    assert (finding.line, finding.col) == (4, 1)


def test_reports_each_dynamic_pagination_clause() -> None:
    source = (
        "SELECT id FROM first_event OFFSET :first_offset;\nSELECT id FROM second_event LIMIT :second_offset, :limit;"
    )

    findings = _check(source)

    assert [(finding.line, finding.col) for finding in findings] == [(1, 28), (2, 29)]


def test_reports_absolute_columns_for_multiple_statements_on_one_line() -> None:
    source = "SELECT id FROM a OFFSET :a; SELECT id FROM b OFFSET :b;"

    findings = _check(source)

    assert [(finding.line, finding.col) for finding in findings] == [(1, 18), (1, 46)]


def test_dollar_quoted_value_does_not_hide_later_clause_on_same_line() -> None:
    source = "SELECT $$payload$$ AS body FROM event OFFSET :offset;"

    assert len(_check(source)) == 1


def test_postgres_bitwise_xor_does_not_hide_later_clause() -> None:
    source = "-- dialect: postgresql\nSELECT flags # mask FROM event OFFSET :offset;"

    assert len(_check(source)) == 1


def test_allows_direction_matched_composite_cursor() -> None:
    source = (
        "SELECT created_at, id FROM event\n"
        "WHERE (created_at, id) < (:cursor_created_at, :cursor_id)\n"
        "ORDER BY created_at DESC, id DESC LIMIT :limit;"
    )

    assert _check(source) == []
