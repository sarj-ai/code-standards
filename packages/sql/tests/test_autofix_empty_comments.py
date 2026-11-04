from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts import RuleId

from sarj_sql_lint.__main__ import main
from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.autofix import fix_source
from sarj_sql_lint.rules.no_migration_comments import NoMigrationComments


_PATH = Path("migrations/001.sql")
_RULE = RuleId("no-migration-comments")


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("--\nSELECT 1;\n", "  \nSELECT 1;\n"),
        ("  -- \t\nSELECT 1;\n", "      \nSELECT 1;\n"),
        ("SELECT 1; --", "SELECT 1;   "),
        ("SELECT '--'; --\n", "SELECT '--';   \n"),
        ("SELECT 1/**/AS value;\n", "SELECT 1    AS value;\n"),
        ("SELECT 1/* \t */AS value;\n", "SELECT 1       AS value;\n"),
        ("SELECT 1/*\n \t\n*/AS value;\n", "SELECT 1  \n  \n  AS value;\n"),
        ("SELECT 1/**//**/AS value;\n", "SELECT 1        AS value;\n"),
        ("SELECT 1-/**/-2;\n", "SELECT 1-    -2;\n"),
        ("SELECT 1/ /**/2;\n", "SELECT 1/     2;\n"),
        ("SELECT 'payload'; SELECT 1/**/AS value;\n", "SELECT 'payload'; SELECT 1    AS value;\n"),
        ("SELECT 'payload' AS label, 1/**/AS value;\n", "SELECT 'payload' AS label, 1    AS value;\n"),
        ("SELECT ';' AS label; SELECT 1/**/AS value;\n", "SELECT ';' AS label; SELECT 1    AS value;\n"),
        ("SELECT '  ' AS label, 1/**/AS value;\n", "SELECT '  ' AS label, 1    AS value;\n"),
        ("SELECT \"it''s\" AS label, 1/**/AS value;\n", "SELECT \"it''s\" AS label, 1    AS value;\n"),
        ("SELECT 'a''b' AS label, 1/**/AS value;\n", "SELECT 'a''b' AS label, 1    AS value;\n"),
        ("SELECT '/**/' AS label, 1/**/AS value;\n", "SELECT '/**/' AS label, 1    AS value;\n"),
        ("SELECT \"'  '\" AS label, 1/**/AS value;\n", "SELECT \"'  '\" AS label, 1    AS value;\n"),
        ("SELECT 'value'; /**/ SELECT 1;\n", "SELECT 'value';      SELECT 1;\n"),
        ("/**/", "    "),
        ("--", "  "),
    ],
)
def test_empty_comments_preserve_sql_tokens_and_converge(source: str, expected: str, ending: str) -> None:
    source = source.replace("\n", ending)
    expected = expected.replace("\n", ending)
    assert NoMigrationComments().check(_PATH, source)

    fixed = fix_source(_PATH, source, rule_ids=[_RULE])

    assert fixed == expected
    before = [
        statement
        for tree in parse_postgres(source)
        if tree is not None and (statement := tree.sql(dialect="postgres", comments=False))
    ]
    after = [
        statement
        for tree in parse_postgres(fixed)
        if tree is not None and (statement := tree.sql(dialect="postgres", comments=False))
    ]
    assert before == after
    assert NoMigrationComments().check(_PATH, fixed) == []
    assert fix_source(_PATH, fixed, rule_ids=[_RULE]) == fixed


@pytest.mark.parametrize(
    "source",
    [
        "SELECT '/**/', '--', '/* */';\n",
        "SELECT 'a'/*\n*/'b';\n",
        "SELECT 'a'\n/**/'b';\n",
        "SELECT 'a'/**/'b';\n",
        "SELECT '  '/**/\n'b';",
        "SELECT ''/**/\n''/**/\n'';",
        "SELECT '  '/**/\n'  ';",
        "SELECT 'a'-- unchanged prose\n/**/'b';",
        "SELECT 'a'/*\n*//**/'b';\n",
        'SELECT "/**/", "--";\n',
        "/*+ */ SELECT 1;\n",
        "/*! */ SELECT 1;\n",
        "/*M! */ SELECT 1;\n",
        "/* /* */ */ SELECT 1;\n",
        "/* migrate:up */ SELECT 1;\n",
        "-- migrate:up\nSELECT 1;\n",
        "-- SPDX-License-Identifier: MIT\nSELECT 1;\n",
        "/* Ordinary migration prose. */ SELECT 1;\n",
        "-- Code generated. DO NOT EDIT.\n/**/ SELECT 1;\n",
        "-- dialect: mysql\n/**/ SELECT 1;\n",
        "-- dialect: sqlite\n/**/ SELECT 1;\n",
        "-- dialect: clickhouse\n/**/ SELECT 1;\n",
        "-- dialect: trino\n/**/ SELECT 1;\n",
        "SELECT $$/**/$$; /**/\n",
        "DO $$ BEGIN /**/ NULL; END $$;\n",
        "COPY t(body) FROM STDIN;\n/**/\n\\.\n",
        "\ufeff/**/ SELECT 1;\n",
        "/**/ SELECT broken (;\n",
        "/*",
        "/* \t",
    ],
)
def test_empty_comment_fix_keeps_unproved_and_owned_sources(source: str) -> None:
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


@pytest.mark.parametrize(
    "selected",
    [None, [_RULE], [RuleId("no-migration-comment-cruft"), _RULE]],
    ids=("default-rules", "migration-comments-only", "combined-comment-rules"),
)
@pytest.mark.parametrize(
    ("comments", "expected"),
    [
        ("-- DROP TABLE legacy;\n--\n", "\n\n"),
        ("--\n-- DROP TABLE legacy;\n", "\n\n"),
        ("-- ========\n--\n", "\n  \n"),
        ("--\n-- ========\n", "  \n\n"),
        ("/**/\n-- DROP TABLE legacy;\n", "    \n\n"),
    ],
)
def test_empty_comments_compose_with_existing_group_fixes(
    selected: list[RuleId] | None, comments: str, expected: str
) -> None:
    source = comments + "SELECT 1;\n"
    fixed = fix_source(_PATH, source, rule_ids=selected)
    assert fixed == expected + "SELECT 1;\n"
    assert fix_source(_PATH, fixed, rule_ids=selected) == fixed


def test_empty_comment_selection_preserves_prose_and_other_rules() -> None:
    source = "-- It's an authored rationale.\n/**/ CREATE TABLE t (body VARCHAR(8));\n"
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source.replace("/**/", "    ")
    assert fix_source(_PATH, source, rule_ids=[]) == source
    assert fix_source(_PATH, source, rule_ids=["no-migration-comment-cruft"]) == source
    assert fix_source(Path("queries/001.sql"), source, rule_ids=[_RULE]) == source


@pytest.mark.parametrize("prefix", [b"", b"\xef\xbb\xbf"])
def test_empty_comment_cli_fix_preserves_custody_and_has_a_noop_second_pass(tmp_path: Path, prefix: bytes) -> None:
    path = tmp_path / _PATH
    path.parent.mkdir()
    path.write_bytes(prefix + b"SELECT 1/*\r\n*/AS value; --\r\n")
    path.chmod(0o640)

    assert main(["check", "--rule", _RULE, "--fix", str(path)]) == 0

    expected = prefix + b"SELECT 1  \r\n  AS value;   \r\n"
    assert path.read_bytes() == expected
    before = path.stat()
    assert before.st_mode & 0o777 == 0o640
    assert main(["check", "--rule", _RULE, "--fix", str(path)]) == 0
    after = path.stat()
    assert path.read_bytes() == expected
    assert (after.st_ino, after.st_mtime_ns, after.st_mode) == (before.st_ino, before.st_mtime_ns, before.st_mode)
