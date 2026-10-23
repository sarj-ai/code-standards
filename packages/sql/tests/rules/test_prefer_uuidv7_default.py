from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.prefer_uuidv7_default import PreferUuidv7Default


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return PreferUuidv7Default().check(Path("migration.sql"), source)


_PUBLIC_EXAMPLES = PreferUuidv7Default.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferUuidv7Default().check(Path(focus.path), focus.source)) == example.expected_count


_LEGACY_UUID_CALL = "gen_random_uuid()"


def _legacy_uuid_sql(template: str) -> str:
    return template.replace("__LEGACY_UUID_CALL__", _LEGACY_UUID_CALL)


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            f"CREATE TABLE IF NOT EXISTS call (id UUID PRIMARY KEY DEFAULT {_LEGACY_UUID_CALL});",
            id="create-table-default",
        ),
        pytest.param(
            f"ALTER TABLE call ALTER COLUMN id SET DEFAULT {_LEGACY_UUID_CALL};",
            id="alter-column-default",
        ),
        pytest.param(
            _legacy_uuid_sql("INSERT INTO call (id) VALUES (__LEGACY_UUID_CALL__) ON CONFLICT DO NOTHING;"),
            id="insert-values",
        ),
        pytest.param(f"SELECT {_LEGACY_UUID_CALL.upper()};", id="uppercase"),
        pytest.param(f"SELECT {_LEGACY_UUID_CALL.replace('(', ' (')};", id="space-before-paren"),
        pytest.param(f"SELECT {_LEGACY_UUID_CALL.replace('(', '\n (')};", id="newline-before-paren"),
        pytest.param(f"SELECT {_LEGACY_UUID_CALL.replace('(', ' /* call */\n (')};", id="comment-before-paren"),
    ],
)
def test_flags_gen_random_uuid(source: str):
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ109"
    assert "uuidv7()" in diags[0].message


def test_reports_each_occurrence():
    src = f"CREATE TABLE t (\n  a UUID DEFAULT {_LEGACY_UUID_CALL},\n  b UUID DEFAULT {_LEGACY_UUID_CALL}\n);"
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
    assert _check(f"SELECT {_LEGACY_UUID_CALL};")[0].col == 8


def test_multiline_call_keeps_the_function_name_location() -> None:
    source = f"SELECT\n  {_LEGACY_UUID_CALL.replace('(', '\n (')};"
    assert [(item.line, item.col) for item in _check(source)] == [(2, 3)]


@pytest.mark.parametrize(
    "source",
    ["SELECT 'gen_random_uuid\n ()';", 'SELECT "gen_random_uuid\n ()" FROM t;', "/* gen_random_uuid\n () */ SELECT 1;"],
)
def test_multiline_call_text_in_noncode_is_preserved(source: str) -> None:
    assert _check(source) == []


def test_flags_schema_qualified_gen_random_uuid():
    assert len(_check(f"SELECT public.{_LEGACY_UUID_CALL};")) == 1


def test_quoted_builtin_function_preserves_detection_and_position() -> None:
    source = 'SELECT "gen_random_uuid"();'
    findings = _check(source)
    assert len(findings) == 1
    assert (findings[0].line, findings[0].col) == (1, 8)


@pytest.mark.parametrize(
    "source", ['SELECT "GEN_RANDOM_UUID"();', 'SELECT "gen_random_uuid()" FROM note;', "SELECT 'gen_random_uuid()';"]
)
def test_case_sensitive_function_and_quoted_call_decoys_are_inert(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("call", ['"gen_random_uuid"()', 'public."gen_random_uuid"\n/* call */ ()'])
def test_flags_a_quoted_native_function_call(call: str) -> None:
    [finding] = _check(f"SELECT {call};")
    assert finding.line == 1


@pytest.mark.parametrize(
    "source",
    [
        'SELECT "GEN_RANDOM_UUID"();',
        'SELECT "gen_random_uuid" FROM item;',
        'SELECT "gen_random_uuid()" FROM item;',
        "SELECT 'gen_random_uuid()';",
    ],
)
def test_does_not_confuse_a_quoted_name_or_value_with_the_native_call(source: str) -> None:
    assert _check(source) == []


def test_dollar_identifier_suffix_does_not_become_a_native_uuid_call() -> None:
    assert _check("SELECT custom$gen_random_uuid();") == []


@pytest.mark.parametrize("prefix", ["α", "café", "a\u0301", "😀", "custom$"])
def test_custom_identifier_suffix_is_not_the_native_uuid_function(prefix: str) -> None:
    assert _check(f"SELECT {prefix}gen_random_uuid();") == []
    assert len(_check(f"SELECT {prefix}.gen_random_uuid();")) == 1


@pytest.mark.parametrize("name", ["gen_random_uu\u0130d", "gen_random_uuid\u00a0"])
def test_unicode_function_names_are_not_native_uuid_calls(name: str) -> None:
    assert PreferUuidv7Default().check(Path("queries.sql"), f"SELECT {name}();") == []
