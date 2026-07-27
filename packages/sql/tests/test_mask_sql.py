"""`mask_sql` masking contract, with dollar-quoted bodies kept as live SQL.

A `$$ ... $$` body in a Postgres migration is a `DO` block or a function body — it
is SQL, not string data — so it must survive masking while genuine string data and
comments are still blanked. These tests pin both halves, plus the invariants every
rule depends on: identical length, identical line count, and no reflow (so the
line-keyed `-- sarj-noqa` suppression keeps working).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.__main__ import main
from sarj_sql_lint.rule_base import dollar_quoted_lines, mask_sql, split_statements


if TYPE_CHECKING:
    from pathlib import Path


def _assert_shape(source: str, masked: str) -> None:
    """Assert the invariants every caller of `mask_sql` relies on."""
    assert len(masked) == len(source)
    assert masked.count("\n") == source.count("\n")
    assert [i for i, c in enumerate(source) if c == "\n"] == [i for i, c in enumerate(masked) if c == "\n"]


def _mask(source: str) -> str:
    masked = mask_sql(source)
    _assert_shape(source, masked)
    return masked


# --------------------------------------------------------------------------
# dollar-quoted bodies are kept as SQL
# --------------------------------------------------------------------------


def test_bare_dollar_body_is_kept_as_sql() -> None:
    masked = _mask("DO $$ UPDATE batch SET x = 1; $$;")
    assert "UPDATE batch SET x = 1;" in masked
    # the delimiters themselves are blanked, so no stray `$` reaches a rule
    assert "$" not in masked


def test_tagged_dollar_body_is_kept_as_sql() -> None:
    source = "CREATE FUNCTION f() RETURNS void AS $func$\nDELETE FROM call;\n$func$ LANGUAGE sql;"
    masked = _mask(source)
    assert "DELETE FROM call;" in masked
    assert "$" not in masked
    assert "LANGUAGE sql;" in masked


def test_uppercase_tag_body_is_kept() -> None:
    masked = _mask("AS $BODY$ ALTER TABLE call ADD COLUMN x TEXT; $BODY$")
    assert "ALTER TABLE call ADD COLUMN x TEXT;" in masked


def test_tag_must_match_to_close() -> None:
    """A `$other$` inside a `$func$` body does not close it."""
    source = "$func$ SELECT 1; $other$ SELECT 2; $func$ SELECT 3;"
    masked = _mask(source)
    # everything is retained; the `$other$` opened a nested quote whose body is
    # also SQL, and only the real `$func$` ended the outer one
    assert "SELECT 1;" in masked
    assert "SELECT 2;" in masked
    assert "SELECT 3;" in masked
    assert "$" not in masked
    # the `$func$` really did close: line is no longer inside a body past it
    assert dollar_quoted_lines(source) == frozenset({1})


def test_unmatched_inner_tag_does_not_steal_the_outer_close() -> None:
    """`$a$ ... $b$ ... $a$` — the outer close pops the dangling inner tag."""
    source = "$a$ x $b$ y $a$ SELECT 9;"
    masked = _mask(source)
    assert masked.endswith(" SELECT 9;")
    assert "$" not in masked


def test_nested_tagged_quote_inside_a_different_tag() -> None:
    source = "$outer$ SELECT 1; $inner$ SELECT 2; $inner$ SELECT 3; $outer$ SELECT 4;"
    masked = _mask(source)
    for kept in ("SELECT 1;", "SELECT 2;", "SELECT 3;", "SELECT 4;"):
        assert kept in masked
    assert "$" not in masked


def test_string_inside_a_dollar_body_is_still_masked() -> None:
    masked = _mask("DO $$ UPDATE t SET s = 'DROP TABLE users'; $$;")
    assert "UPDATE t SET s =" in masked
    assert "DROP TABLE users" not in masked


def test_comment_inside_a_dollar_body_is_still_masked() -> None:
    source = "DO $$\n-- Update the batch table\nUPDATE batch SET x = 1;\n$$;"
    masked = _mask(source)
    assert "UPDATE batch SET x = 1;" in masked
    assert "Update the batch table" not in masked


def test_empty_dollar_body() -> None:
    assert _mask("SELECT $$$$;") == "SELECT     ;"


# --------------------------------------------------------------------------
# things that look like dollar quotes but are not
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "SELECT * FROM t WHERE a = $1;",
        "SELECT * FROM t WHERE a = $1 AND b = $2;",
        "EXECUTE stmt USING $1, $2, $3;",
        "SELECT $1$2;",
        "SELECT $12345;",
    ],
)
def test_positional_parameters_do_not_open_a_dollar_quote(source: str) -> None:
    """`$1`/`$2` are parameters: a dollar-quote tag can never start with a digit."""
    assert _mask(source) == source


@pytest.mark.parametrize(
    "source",
    [
        "SELECT total$amount FROM t;",
        "SELECT foo$bar$ FROM t;",
        "SELECT a$b$c$d$ FROM t;",
        "ALTER TABLE t RENAME COLUMN x$y TO x$z;",
    ],
)
def test_dollar_in_an_identifier_does_not_open_a_dollar_quote(source: str) -> None:
    """Postgres allows `$` as a non-leading identifier char — it opens nothing."""
    assert _mask(source) == source


def test_parameter_next_to_a_real_dollar_quote() -> None:
    """The `$1` must not disturb the surrounding `$$` body."""
    source = "DO $$ EXECUTE format($fmt$UPDATE t SET a = %s$fmt$, $1); $$;"
    masked = _mask(source)
    assert "UPDATE t SET a = %s" in masked
    assert masked.count("$1") == 1


def test_lone_dollar_is_literal() -> None:
    assert _mask("SELECT '$' , $ , 1;") == "SELECT     , $ , 1;"


# --------------------------------------------------------------------------
# comments win over dollar quotes
# --------------------------------------------------------------------------


def test_dollar_quote_inside_a_line_comment_opens_nothing() -> None:
    source = "-- a $$ b\nCREATE TABLE t (id INT);\n"
    masked = _mask(source)
    assert not masked.splitlines()[0].strip()
    assert "CREATE TABLE t (id INT);" in masked
    assert dollar_quoted_lines(source) == frozenset()


def test_dollar_quote_inside_a_block_comment_opens_nothing() -> None:
    source = "/* a $$ b */ CREATE TABLE t (id INT);\n"
    masked = _mask(source)
    assert "CREATE TABLE t (id INT);" in masked
    assert "$" not in masked
    assert dollar_quoted_lines(source) == frozenset()


def test_dollar_quote_inside_a_string_literal_opens_nothing() -> None:
    source = "INSERT INTO t VALUES ('$$ DROP TABLE users; $$');"
    masked = _mask(source)
    assert "INSERT INTO t VALUES (" in masked
    assert "DROP TABLE users" not in masked
    assert dollar_quoted_lines(source) == frozenset()


# --------------------------------------------------------------------------
# unterminated input must terminate, and must not swallow the file
# --------------------------------------------------------------------------


def test_unterminated_dollar_quote_keeps_the_rest_as_sql() -> None:
    source = "DO $$\nUPDATE batch SET x = 1;\nCREATE TABLE t (id INT);\n"
    masked = _mask(source)
    assert "UPDATE batch SET x = 1;" in masked
    assert "CREATE TABLE t (id INT);" in masked


def test_unterminated_tagged_dollar_quote_keeps_the_rest_as_sql() -> None:
    masked = _mask("AS $body$\nDELETE FROM call;\n")
    assert "DELETE FROM call;" in masked


def test_pathological_unterminated_tags_do_not_recurse_or_hang() -> None:
    """Many nested unterminated tags: an explicit stack, so no recursion limit."""
    source = "".join(f"$t{i}$ SELECT {i};\n" for i in range(2000))
    masked = _mask(source)
    assert "SELECT 1999;" in masked


def test_unterminated_string_and_comment_still_terminate() -> None:
    assert _mask("SELECT 'abc") == "SELECT     "
    assert _mask("/* abc") == "      "


# --------------------------------------------------------------------------
# ordinary literals and identifiers are masked exactly as before
# --------------------------------------------------------------------------


def test_string_literal_is_masked() -> None:
    assert _mask("SELECT 'DROP TABLE t';") == "SELECT               ;"


def test_doubled_quote_escape_keeps_the_scanner_inside_the_literal() -> None:
    masked = _mask("SELECT 'it''s DROP TABLE t' , 1;")
    assert "DROP TABLE" not in masked
    assert masked.endswith(" , 1;")


def test_quoted_identifier_is_masked() -> None:
    masked = _mask('CREATE TABLE "DROP TABLE" (id INT);')
    assert masked.count("DROP TABLE") == 0
    assert "CREATE TABLE " in masked


def test_line_and_block_comments_are_masked() -> None:
    masked = _mask("SELECT 1; -- DROP TABLE t\n/* DROP TABLE u */ SELECT 2;\n")
    assert "DROP TABLE" not in masked
    assert "SELECT 1;" in masked
    assert "SELECT 2;" in masked


def test_semicolon_inside_a_literal_does_not_split_statements() -> None:
    assert len(split_statements(_mask("INSERT INTO t VALUES ('a;b');"))) == 1


# --------------------------------------------------------------------------
# line-number stability (the `-- sarj-noqa` contract)
# --------------------------------------------------------------------------


def test_line_numbers_are_stable_across_a_multiline_dollar_body() -> None:
    source = (
        "-- migrate:up\n"
        "DO $$\n"
        "BEGIN\n"
        "    -- a comment with a ; and a ' in it\n"
        "    UPDATE batch SET x = 1;\n"
        "    ALTER TABLE call ADD COLUMN y TEXT;\n"
        "END $$;\n"
        "CREATE INDEX idx ON call (y);\n"
    )
    masked = _mask(source)
    lines = masked.splitlines()
    assert len(lines) == 8
    assert "UPDATE batch SET x = 1;" in lines[4]
    assert "ALTER TABLE call ADD COLUMN y TEXT;" in lines[5]
    assert "CREATE INDEX idx ON call (y);" in lines[7]
    # every line keeps its original width, so columns are stable too
    assert [len(line) for line in lines] == [len(line) for line in source.splitlines()]


def test_noqa_inside_a_dollar_body_still_suppresses(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End-to-end: the body is now linted, and `-- sarj-noqa` on its line still wins."""
    f = tmp_path / "m.sql"
    _ = f.write_text(
        "DO $$\nBEGIN\n  x TIMESTAMP;\n  y TIMESTAMP; -- sarj-noqa: SARJ101\nEND $$;\n",
        encoding="utf-8",
    )
    assert main(["check", "--rule", "enforce-timestamptz", str(f)]) == 1
    reported = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(reported) == 1
    assert ":3:" in reported[0]


# --------------------------------------------------------------------------
# dollar_quoted_lines
# --------------------------------------------------------------------------


def test_dollar_quoted_lines_covers_the_body_and_its_delimiters() -> None:
    source = "SELECT 1;\nDO $$\nUPDATE t SET a = 1;\nEND $$;\nSELECT 2;\n"
    assert dollar_quoted_lines(source) == frozenset({2, 3, 4})


def test_dollar_quoted_lines_handles_two_bodies() -> None:
    source = "$$ a $$\nSELECT 1;\n$b$ c\nd $b$\n"
    assert dollar_quoted_lines(source) == frozenset({1, 3, 4})


def test_dollar_quoted_lines_unterminated_runs_to_end_of_file() -> None:
    assert dollar_quoted_lines("SELECT 1;\nDO $$\nUPDATE t;\n") == frozenset({2, 3})


def test_dollar_quoted_lines_empty_when_there_are_none() -> None:
    assert dollar_quoted_lines("SELECT $1, total$amount FROM t;\n") == frozenset()
