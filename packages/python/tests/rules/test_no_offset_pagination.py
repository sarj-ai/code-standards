from pathlib import Path

import pytest

from sarj_python_lint.rule_base import Diagnostic, is_suppressed
from sarj_python_lint.rules.no_offset_pagination import NoOffsetPagination


def _check(source: str, path: str = "call_store.py") -> list[Diagnostic]:
    return NoOffsetPagination().check(Path(path), source)


def _kept(source: str, path: str = "call_store.py") -> list[Diagnostic]:
    diags = _check(source, path)
    lines = source.splitlines()
    return [d for d in diags if not is_suppressed(lines, d.line, d.code)]


FIRES = {
    "limit_param_offset_param": 'q = "LIMIT %s OFFSET %s"\n',
    "limit_digit_offset_digit": 'q = "LIMIT 10 OFFSET 20"\n',
    "offset_named_colon": 'q = "OFFSET :cursor"\n',
    "offset_named_at": 'q = "OFFSET @offset"\n',
    "offset_positional_dollar": 'q = "OFFSET $1"\n',
    "offset_pyformat_named": 'q = "OFFSET %(page)s"\n',
    "full_select_query": 'q = "SELECT id, status FROM call ORDER BY created_at LIMIT %s OFFSET %s"\n',
    "offset_bare_digit": 'q = "SELECT id FROM call OFFSET 40"\n',
    "offset_no_leading_limit": 'q = "SELECT id FROM call ORDER BY id OFFSET %s"\n',
}


@pytest.mark.parametrize("source", FIRES.values(), ids=list(FIRES))
def test_fires_one_diagnostic(source: str):
    assert len(_check(source)) == 1


ALLOWS = {
    "prose_no_value_token": 'msg = "no base offset applied"\n',
    "offset_as_dict_key": 'd = {"offset": cursor}\n',
    "offset_masked_string_value": "q = \"SELECT note FROM call WHERE note = 'OFFSET 5'\"\n",
    "bigquery_with_offset": 'q = "SELECT msg FROM UNNEST(arr) WITH OFFSET AS msg_offset"\n',
    "python_var_named_offset": "offset = 20\nrows = fetch(offset)\n",
    "line_comment_offset": 'q = "SELECT id FROM call ORDER BY id -- LIMIT %s OFFSET %s"\n',
    "block_comment_offset": 'q = "SELECT id FROM call /* OFFSET 10 */ ORDER BY id"\n',
    "fstring_offset_interp_only": 'q = f"SELECT id FROM call LIMIT {n} OFFSET {offset}"\n',
    "offset_word_then_prose": 'q = "the offset value was recomputed"\n',
    "empty_string": 'q = ""\n',
    "bytes_literal": 'q = b"LIMIT %s OFFSET %s"\n',
}


@pytest.mark.parametrize("source", ALLOWS.values(), ids=list(ALLOWS))
def test_does_not_fire(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'q = base + " LIMIT %s OFFSET %s"\n',
        'q = "SELECT id FROM call" + " LIMIT %s OFFSET %s"\n',
        'q = "SELECT id FROM call ORDER BY id " "LIMIT %s OFFSET %s"\n',
    ],
    ids=["var_plus_fragment", "string_plus_string", "implicit_adjacent"],
)
def test_flags_concatenated_queries(source: str):
    assert len(_check(source)) == 1


def test_fires_on_multiline_triple_quoted():
    src = 'q = """\nSELECT id\nFROM call\nORDER BY created_at\nLIMIT %s OFFSET %s\n"""\n'
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "source",
    [
        'q = "OFFSET %s"\n',
        'q = "offset %s"\n',
        'q = "Offset %s"\n',
        'q = "OfFsEt 5"\n',
    ],
    ids=["upper", "lower", "title", "mixed"],
)
def test_case_insensitive(source: str):
    assert len(_check(source)) == 1


def test_message_and_code_fields():
    diags = _check('q = "LIMIT %s OFFSET %s"\n')
    assert len(diags) == 1
    assert diags[0].code == "SARJ025"
    assert "OFFSET" in diags[0].message
    assert "keyset cursor" in diags[0].message
    assert "sarj-noqa: SARJ025" in diags[0].message


def test_line_and_col_single():
    diags = _check('x = 1\nq = "LIMIT %s OFFSET %s"\n')
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].col == 5


def test_line_and_col_of_multiline_at_string_start():
    diags = _check('a = 1\nb = 2\nq = """\nLIMIT %s OFFSET %s\n"""\n')
    assert len(diags) == 1
    assert diags[0].line == 3
    assert diags[0].col == 5


def test_two_violations_sorted_by_line():
    src = 'a = "LIMIT %s OFFSET %s"\nb = "LIMIT 5 OFFSET 10"\n'
    diags = _check(src)
    assert [(d.line, d.col) for d in diags] == [(1, 5), (2, 5)]


def test_two_violations_same_line_sorted_by_col():
    src = 't = ("LIMIT %s OFFSET %s", "OFFSET :c")\n'
    diags = _check(src)
    assert [(d.line, d.col) for d in diags] == [(1, 6), (1, 28)]


def test_reports_all_violations_in_file():
    src = (
        'a = "SELECT id FROM call LIMIT %s OFFSET %s"\n'
        'b = "SELECT id FROM call WHERE id > %s ORDER BY id LIMIT %s"\n'
        'c = "SELECT id FROM call OFFSET 100"\n'
    )
    diags = _check(src)
    assert [d.line for d in diags] == [1, 3]


@pytest.mark.parametrize(
    "source",
    [
        'q = "LIMIT %s OFFSET %s"  # sarj-noqa\n',
        'q = "LIMIT %s OFFSET %s"  # sarj-noqa: SARJ025\n',
        'q = "LIMIT %s OFFSET %s"  # sarj-noqa: SARJ024, SARJ025\n',
    ],
    ids=["bare", "exact_code", "multi_code"],
)
def test_respects_noqa(source: str):
    assert _kept(source) == []


def test_wrong_noqa_code_not_suppressed():
    src = 'q = "LIMIT %s OFFSET %s"  # sarj-noqa: SARJ024\n'
    assert len(_kept(src)) == 1


@pytest.mark.parametrize("path", ["call_store.py", "stores/call.py"])
def test_store_file_flagged(path: str):
    assert len(_check('q = "LIMIT %s OFFSET %s"\n', path=path)) == 1


@pytest.mark.parametrize("path", ["app/views.py", "blog.py", "sqlalchemy/sql/compiler.py"])
def test_nonstore_file_not_flagged(path: str):
    assert _check('q = "LIMIT %s OFFSET %s"\n', path=path) == []


@pytest.mark.parametrize(
    "source",
    ["", "   \n\t\n", "# only a comment\n", "x = 1 + 2\n", 'name = "no sql here"\n'],
    ids=["empty", "whitespace", "comment_only", "no_strings", "plain_string"],
)
def test_boundary_inputs_return_empty(source: str):
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    ["def (:\n", "q = 'LIMIT %s OFFSET %s\n", "class A(:\n    pass\n"],
    ids=["bad_def", "unterminated_string", "bad_class"],
)
def test_syntax_error_returns_empty(source: str):
    assert _check(source) == []


# --------------------------------------------------------------------------- #
# Cross-package parity with SARJ107 and the TS twin                            #
# (`packages/sql/.../no_limit_offset.py`,                                      #
#  `packages/typescript/src/rules/no-offset-pagination.ts`).                   #
# All three share ONE parameter alternation. `?` was missing here, so every    #
# sqlite3 / aiosqlite store paginating with `LIMIT ? OFFSET ?` was a silent    #
# false negative while the TS twin caught it.                                  #
# --------------------------------------------------------------------------- #

PARAM_MARKERS = {
    "pyformat": 'q = "SELECT id FROM t ORDER BY id LIMIT %s OFFSET %s"\n',
    "pyformat_named": 'q = "SELECT id FROM t ORDER BY id LIMIT %(n)s OFFSET %(off)s"\n',
    "qmark": 'q = "SELECT id FROM t ORDER BY id LIMIT ? OFFSET ?"\n',
    "numbered_qmark": 'q = "SELECT id FROM t ORDER BY id LIMIT ?1 OFFSET ?2"\n',
    "named_colon": 'q = "SELECT id FROM t ORDER BY id LIMIT :n OFFSET :off"\n',
    "named_at": 'q = "SELECT id FROM t ORDER BY id LIMIT @n OFFSET @off"\n',
    "numeric_dollar": 'q = "SELECT id FROM t ORDER BY id LIMIT $1 OFFSET $2"\n',
    "bare_digit": 'q = "SELECT id FROM t ORDER BY id LIMIT 10 OFFSET 20"\n',
}


@pytest.mark.parametrize("source", PARAM_MARKERS.values(), ids=list(PARAM_MARKERS))
def test_every_shared_param_marker_is_detected(source: str):
    assert len(_check(source)) == 1


NON_PAGINATION = {
    "bigquery_with_offset": 'q = "SELECT x, i FROM UNNEST(arr) AS x WITH OFFSET AS i"\n',
    "english_word": 'msg = "the offset is out of range for this window"\n',
    "column_named_offset": 'q = "ALTER TABLE t ADD COLUMN offset INTEGER NOT NULL DEFAULT 0"\n',
}


@pytest.mark.parametrize("source", NON_PAGINATION.values(), ids=list(NON_PAGINATION))
def test_offset_without_a_value_token_is_not_pagination(source: str):
    """Requiring the value token is the shared reason all three packages stay quiet here."""
    assert _check(source) == []
