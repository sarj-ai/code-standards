from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.__main__ import analyze, main
from sarj_sql_lint.rule_base import dollar_quoted_lines, mask_sql, normalize_sql_identifier, split_statements


if TYPE_CHECKING:
    from pathlib import Path


def _assert_shape(source: str, masked: str) -> None:
    assert len(masked) == len(source)
    assert masked.count("\n") == source.count("\n")
    assert [i for i, c in enumerate(source) if c == "\n"] == [i for i, c in enumerate(masked) if c == "\n"]


def _mask(source: str) -> str:
    masked = mask_sql(source)
    _assert_shape(source, masked)
    return masked


def test_bare_dollar_body_is_kept_as_sql() -> None:
    masked = _mask("DO $$ UPDATE batch SET x = 1; $$;")
    assert "UPDATE batch SET x = 1;" in masked
    # the delimiters themselves are blanked, so no stray `$` reaches a rule
    assert "$" not in masked


def test_opt_in_masks_scalar_dollar_strings_and_preserves_shape() -> None:
    source = "SELECT $doc$; CREATE FUNCTION example()\n$doc$;\nSELECT 1;"
    masked = mask_sql(source, mask_dollar_literals=True)
    _assert_shape(source, masked)
    assert "CREATE FUNCTION" not in masked
    assert "SELECT 1;" in masked


def test_opt_in_keeps_executable_do_but_masks_nested_dollar_values() -> None:
    source = "DO $$ BEGIN RAISE NOTICE $doc$CREATE TRIGGER example$doc$; CREATE TRIGGER audit AFTER INSERT ON batch EXECUTE FUNCTION audit(); END $$;"
    masked = mask_sql(source, mask_dollar_literals=True)
    _assert_shape(source, masked)
    assert "CREATE TRIGGER example" not in masked
    assert "CREATE TRIGGER audit" in masked


def test_opt_in_does_not_change_the_legacy_masking_mode() -> None:
    source = "SELECT $$CREATE TRIGGER example$$;"
    assert "CREATE TRIGGER example" in mask_sql(source)
    assert "CREATE TRIGGER example" not in mask_sql(source, mask_dollar_literals=True)
    assert "CREATE TRIGGER example" in mask_sql(source)


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
    source = "$a$ x $b$ y $a$ SELECT 9;"
    masked = _mask(source)
    assert masked.endswith(" SELECT 9;")
    assert "$" not in masked


@pytest.mark.parametrize("kept", ["SELECT 1;", "SELECT 2;", "SELECT 3;", "SELECT 4;"])
def test_nested_tagged_quote_inside_a_different_tag(kept: str) -> None:
    source = "$outer$ SELECT 1; $inner$ SELECT 2; $inner$ SELECT 3; $outer$ SELECT 4;"
    masked = _mask(source)
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
    assert _mask(source) == source


def test_parameter_next_to_a_real_dollar_quote() -> None:
    source = "DO $$ EXECUTE format($fmt$UPDATE t SET a = %s$fmt$, $1); $$;"
    masked = _mask(source)
    assert "UPDATE t SET a = %s" in masked
    assert masked.count("$1") == 1


def test_lone_dollar_is_literal() -> None:
    assert _mask("SELECT '$' , $ , 1;") == "SELECT     , $ , 1;"


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


def test_unterminated_dollar_quote_keeps_the_rest_as_sql() -> None:
    source = "DO $$\nUPDATE batch SET x = 1;\nCREATE TABLE t (id INT);\n"
    masked = _mask(source)
    assert "UPDATE batch SET x = 1;" in masked
    assert "CREATE TABLE t (id INT);" in masked


def test_unterminated_tagged_dollar_quote_keeps_the_rest_as_sql() -> None:
    masked = _mask("AS $body$\nDELETE FROM call;\n")
    assert "DELETE FROM call;" in masked


def test_pathological_unterminated_tags_do_not_recurse_or_hang() -> None:
    source = "".join(f"$t{i}$ SELECT {i};\n" for i in range(2000))
    masked = _mask(source)
    assert "SELECT 1999;" in masked


def test_unterminated_string_and_comment_still_terminate() -> None:
    assert _mask("SELECT 'abc") == "SELECT     "
    assert _mask("/* abc") == "      "


def test_string_literal_is_masked() -> None:
    assert _mask("SELECT 'DROP TABLE t';") == "SELECT               ;"


@pytest.mark.parametrize(
    ("source", "hidden", "suffix"),
    [
        ("SELECT 'it''s DROP TABLE t' , 1;", "DROP TABLE", " , 1;"),
        ("SELECT E'it\\'s TIMESTAMP', TIMESTAMPTZ;", "TIMESTAMP'", "TIMESTAMPTZ;"),
    ],
    ids=[
        "doubled-quote-escape-keeps-the-scanner-inside-the-literal",
        "postgres-escape-string-keeps-backslash-escaped-quote-inside-literal",
    ],
)
def test_literal_escape_keeps_the_scanner_inside_the_literal(source: str, hidden: str, suffix: str) -> None:
    masked = _mask(source)
    assert hidden not in masked
    assert masked.endswith(suffix)


def test_quoted_identifier_is_masked() -> None:
    masked = _mask('CREATE TABLE "DROP TABLE" (id INT);')
    assert masked.count("DROP TABLE") == 0
    assert "CREATE TABLE " in masked


def test_line_and_block_comments_are_masked() -> None:
    masked = _mask("SELECT 1; -- DROP TABLE t\n/* DROP TABLE u */ SELECT 2;\n")
    assert "DROP TABLE" not in masked
    assert "SELECT 1;" in masked
    assert "SELECT 2;" in masked


def test_nested_postgres_block_comments_are_wholly_masked() -> None:
    source = "/* outer /* inner */ TIMESTAMP */ CREATE TABLE t(created_at TIMESTAMPTZ);"
    masked = _mask(source)

    assert "outer" not in masked
    assert "inner" not in masked
    assert "TIMESTAMP */" not in masked
    assert masked.endswith("CREATE TABLE t(created_at TIMESTAMPTZ);")


def test_unterminated_nested_postgres_block_comment_terminates_safely() -> None:
    assert not _mask("/* outer /* inner */ TIMESTAMP").strip()


def test_semicolon_inside_a_literal_does_not_split_statements() -> None:
    assert len(split_statements(_mask("INSERT INTO t VALUES ('a;b');"))) == 1


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
    f = tmp_path / "m.sql"
    f.write_text(
        "DO $$\nBEGIN\n  x TIMESTAMP;\n  y TIMESTAMP; -- sarj-noqa: SARJ101\nEND $$;\n",
        encoding="utf-8",
    )
    assert main(["check", "--rule", "enforce-timestamptz", str(f)]) == 1
    reported = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(reported) == 1
    assert ":3:" in reported[0]


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


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_statement_boundaries_ignore_semicolons_inside_quoted_identifiers(ending: str) -> None:
    source = ending.join(['SELECT "a;b";', 'SELECT "escaped"";name";'])
    statements = split_statements(source)
    assert len(statements) == 2
    assert statements[0] == [(1, 'SELECT "a;b"')]
    assert statements[1] == [(2, 'SELECT "escaped"";name"')]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('"a . b"', '"a . b"'),
        ('"A"."b"', '"A".b'),
        (' PUBLIC . "plan" ', "public.plan"),
        ("<unnamed>", "<unnamed>"),
        ("a-b", "a-b"),
        ("a..b", "a..b"),
    ],
)
def test_identifier_normalization_preserves_quoted_identity_and_unparsed_text(source: str, expected: str) -> None:
    assert normalize_sql_identifier(source) == expected


@pytest.mark.parametrize(
    ("rule_id", "source"),
    [
        ("enforce-timestamptz", "CREATE TABLE orders (created_at TIMESTAMP);"),
        ("idempotent-ddl", "CREATE TABLE orders (id INT);"),
        ("no-pg-enum", "CREATE TYPE status AS ENUM ('ready');"),
        ("prefer-text-over-varchar", "CREATE TABLE orders (name VARCHAR(100));"),
        ("insert-requires-replay-policy", "INSERT INTO orders (id) VALUES (1);"),
        ("prefer-jsonb", "CREATE TABLE orders (payload JSON);"),
        ("index-concurrently", "CREATE INDEX orders_idx ON orders(id);"),
        ("no-application-schema-check", "CREATE TABLE orders (status TEXT CHECK (status IN ('ready', 'done')));"),
        (
            "prefer-uuidv7-default",
            "CREATE TABLE orders (id UUID DEFAULT gen_random_uuid());",  # sarj-noqa: SARJ053 -- intentional positive SQL rule fixture
        ),
        ("require-lock-timeout", "ALTER TABLE orders ADD COLUMN note TEXT;"),
        ("require-fk-index", "CREATE TABLE orders (owner_id INT REFERENCES owners(id) ON DELETE CASCADE);"),
        ("no-migration-comment-cruft", "-- ALTER TABLE orders ADD COLUMN note TEXT;"),
    ],
)
def test_scalar_dollar_data_is_not_an_executable_migration(tmp_path: Path, rule_id: str, source: str) -> None:
    path = tmp_path / "supabase" / "migrations" / "001_orders.sql"
    path.parent.mkdir(parents=True)
    path.write_text(source + "\n")
    assert len(analyze([rule_id], [path])) == 1
    path.write_text(f"SELECT $data${source}$data$;\n")
    assert analyze([rule_id], [path]) == []


@pytest.mark.parametrize(
    "source",
    [
        "DO $$ BEGIN CREATE TYPE status AS ENUM ('ready'); END $$;",
        "CREATE FUNCTION define_status() RETURNS void AS $$ BEGIN CREATE TYPE status AS ENUM ('ready'); END $$ LANGUAGE plpgsql;",
    ],
)
def test_executable_dollar_bodies_retain_migration_findings(tmp_path: Path, source: str) -> None:
    path = tmp_path / "migration.sql"
    path.write_text(source)
    assert len(analyze(["no-pg-enum"], [path])) == 1


def test_scalar_sibling_index_does_not_cover_a_real_foreign_key(tmp_path: Path) -> None:
    project = tmp_path / "supabase" / "migrations"
    project.mkdir(parents=True)
    source = project / "001_orders.sql"
    source.write_text("CREATE TABLE orders (owner_id BIGINT REFERENCES owners(id) ON DELETE CASCADE);\n")
    (project / "002_data.sql").write_text("SELECT $$CREATE INDEX orders_owner_idx ON orders(owner_id);$$;\n")
    assert len(analyze(["require-fk-index"], [source])) == 1


def test_scalar_timeout_does_not_protect_executable_ddl(tmp_path: Path) -> None:
    source = tmp_path / "supabase" / "migrations" / "001_orders.sql"
    source.parent.mkdir(parents=True)
    source.write_text(
        "-- dialect: postgres\nSELECT $$SET lock_timeout = '5s';$$;\nALTER TABLE orders ADD COLUMN note TEXT;\n"
    )
    assert [(finding.code, finding.line) for finding in analyze(["require-lock-timeout"], [source])] == [("SARJ110", 3)]
