from __future__ import annotations

from pathlib import Path

import pytest
from sqlglot import exp

from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.autofix import fix_source
from sarj_sql_lint.rule_base import physical_lines, source_location
from sarj_sql_lint.rules import REGISTRY


_SEPARATORS = ["\u2028", "\x85", "\f", "\u2029"]


@pytest.mark.parametrize("separator", _SEPARATORS)
@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_real_banner_fix_preserves_parsed_unicode_literal(separator: str, ending: str) -> None:
    path = Path("migrations/20261024_physical_lines.sql")
    literal = f"before{separator}-- ========{separator}after"
    statement = f"SELECT '{literal}' AS payload;{ending}"
    source = f"{statement}-- ========{ending}"
    rule_id = "no-migration-comment-cruft"
    native = REGISTRY[rule_id]()
    findings = native.check(path, source)
    assert len(findings) == 1
    assert findings[0].line == 2

    fixed = fix_source(path, source, rule_ids=[rule_id])

    assert fixed == statement + ending
    assert _string_literals(source) == _string_literals(fixed) == (literal,)
    assert native.check(path, fixed) == []
    assert fix_source(path, fixed, rule_ids=[rule_id]) == fixed


def _string_literals(source: str) -> tuple[str, ...]:
    parsed = parse_postgres(source)
    assert parsed
    assert all(tree is not None for tree in parsed)
    return tuple(
        node.name for tree in parsed if tree is not None for node in tree.find_all(exp.Literal) if node.is_string
    )


@pytest.mark.parametrize("separator", _SEPARATORS)
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_literal_type_fix_uses_physical_diagnostic_position(separator: str, ending: str) -> None:
    path = Path("migrations/20261024_physical_lines.sql")
    prefix = f"SELECT 'before{separator}after' AS banner,{ending}"
    source = prefix + "  CAST(CAST('value' AS pg_catalog.varchar(8)) AS pg_catalog.text) AS value;" + ending
    rule_id = "prefer-text-over-varchar"
    native = REGISTRY[rule_id]()
    assert len(native.check(path, source)) == 1

    fixed = fix_source(path, source, rule_ids=[rule_id])

    assert fixed == source.replace("pg_catalog.varchar(8)", "pg_catalog.text")
    assert _string_literals(source) == _string_literals(fixed)
    assert native.check(path, fixed) == []
    assert fix_source(path, fixed, rule_ids=[rule_id]) == fixed


@pytest.mark.parametrize("separator", _SEPARATORS)
@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
def test_physical_lines_match_sql_locations_without_losing_bytes(separator: str, ending: str) -> None:
    first = f"SELECT 'a{separator}b';{ending}"
    source = first + "SELECT 2;"
    assert physical_lines(source, keepends=True) == [first, "SELECT 2;"]
    assert "".join(physical_lines(source, keepends=True)) == source
    assert source_location(source, len(first)) == (2, 1)


@pytest.mark.parametrize("separator", _SEPARATORS)
@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_long_disabled_sql_comment_fix_uses_physical_comment_groups(separator: str, ending: str) -> None:
    prefix = f"SELECT 'before{separator}after' AS banner;{ending}"
    comments = ending.join(
        (
            "-- CREATE TABLE users (id BIGINT PRIMARY KEY, name TEXT);",
            "-- CREATE TABLE groups (id BIGINT PRIMARY KEY, name TEXT);",
            "-- CREATE TABLE teams (id BIGINT PRIMARY KEY, name TEXT);",
            "-- CREATE TABLE accounts (id BIGINT PRIMARY KEY, name TEXT);",
            "",
        )
    )
    source = prefix + comments
    path = Path("migrations/20261024_physical_lines.sql")
    rule_id = "no-long-migration-narration"
    native = REGISTRY[rule_id]()
    assert len(native.check(path, source)) == 1

    fixed = fix_source(path, source, rule_ids=[rule_id])

    assert fixed == prefix + ending * 4
    assert _string_literals(source) == _string_literals(fixed)
    assert native.check(path, fixed) == []
    assert fix_source(path, fixed, rule_ids=[rule_id]) == fixed
