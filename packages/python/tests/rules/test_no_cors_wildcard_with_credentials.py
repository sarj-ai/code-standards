from pathlib import Path
from typing import TYPE_CHECKING

from sarj_python_lint.rules.no_cors_wildcard_with_credentials import (
    NoCorsWildcardWithCredentials,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return NoCorsWildcardWithCredentials().check(Path("app.py"), source)


def _count(source: str) -> int:
    return len(_check(source))


# Positive: `"*"` in allow_origins + allow_credentials=True.


def test_flags_bare_wildcard_list():
    src = 'app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)\n'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ028"


def test_flags_ifexp_else_wildcard_branch():
    """The real first-party pattern: `allowed if flag else ["*"]`."""
    src = (
        "app.add_middleware(\n"
        "    CORSMiddleware,\n"
        '    allow_origins=allowed if cors_enforce else ["*"],\n'
        "    allow_credentials=True,\n"
        ")\n"
    )
    assert _count(src) == 1


def test_flags_ifexp_wildcard_in_then_branch():
    src = 'add_middleware(allow_origins=["*"] if debug else allowed, allow_credentials=True)\n'
    assert _count(src) == 1


def test_flags_wildcard_bound_variable_free_list():
    src = 'add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)\n'
    assert _count(src) == 1


def test_flags_wildcard_tuple():
    src = 'add_middleware(CORSMiddleware, allow_origins=("*",), allow_credentials=True)\n'
    assert _count(src) == 1


def test_flags_wildcard_alongside_explicit_origins():
    src = 'add_middleware(allow_origins=["https://x", "*"], allow_credentials=True)\n'
    assert _count(src) == 1


def test_flags_when_credentials_before_origins():
    """Keyword order does not matter."""
    src = 'add_middleware(allow_credentials=True, allow_origins=["*"])\n'
    assert _count(src) == 1


def test_flags_nested_wildcard_deep_in_subtree():
    src = 'add_middleware(allow_origins=[extra, ["*"]], allow_credentials=True)\n'
    assert _count(src) == 1


def test_message_mentions_credentials():
    diags = _check('add_middleware(allow_origins=["*"], allow_credentials=True)\n')
    assert len(diags) == 1
    assert "allow_credentials" in diags[0].message


def test_flags_explicit_cors_middleware_callee():
    src = 'CORSMiddleware(app, allow_origins=["*"], allow_credentials=True)\n'
    assert _count(src) == 1


# Negative: must NOT fire.


def test_allows_explicit_origins_with_credentials():
    src = 'add_middleware(allow_origins=["https://x"], allow_credentials=True)\n'
    assert _check(src) == []


def test_allows_wildcard_with_credentials_false():
    src = 'add_middleware(allow_origins=["*"], allow_credentials=False)\n'
    assert _check(src) == []


def test_allows_wildcard_without_credentials_kwarg():
    src = 'add_middleware(allow_origins=["*"])\n'
    assert _check(src) == []


def test_allows_dynamic_origins_variable():
    """`allow_origins=origins_var` has no `"*"` literal — must not fire."""
    src = "add_middleware(allow_origins=origins_var, allow_credentials=True)\n"
    assert _check(src) == []


def test_allows_dynamic_origins_comprehension_no_star():
    """The first-party comprehension shape: `[str(o) for o in allowed_origins]` — no `"*"` literal."""
    src = "add_middleware(allow_origins=[str(o) for o in allowed_origins], allow_credentials=True)\n"
    assert _check(src) == []


def test_allows_credentials_true_but_no_origins_kwarg():
    src = "add_middleware(allow_credentials=True)\n"
    assert _check(src) == []


def test_allows_star_in_unrelated_call():
    src = 'print("*")\n'
    assert _check(src) == []


def test_allows_star_in_unrelated_kwarg():
    """A `"*"` under a different keyword (not allow_origins) does not fire."""
    src = 'add_middleware(allow_methods=["*"], allow_origins=["https://x"], allow_credentials=True)\n'
    assert _check(src) == []


def test_allows_credentials_truthy_int_not_literal_true():
    """`allow_credentials=1` is not the literal `True` — do not fire."""
    src = 'add_middleware(allow_origins=["*"], allow_credentials=1)\n'
    assert _check(src) == []


def test_allows_credentials_dynamic_expression():
    src = 'add_middleware(allow_origins=["*"], allow_credentials=flag)\n'
    assert _check(src) == []


def test_allows_bytes_star_not_string_star():
    src = 'add_middleware(allow_origins=[b"*"], allow_credentials=True)\n'
    assert _check(src) == []


# Edge cases.


def test_empty_source():
    assert _check("") == []


def test_whitespace_only_source():
    assert _check("\n\n   \n") == []


def test_syntax_error_returns_empty():
    assert _check("add_middleware(allow_origins=[\n") == []


def test_multiple_calls_each_flagged():
    src = (
        'add_middleware(allow_origins=["*"], allow_credentials=True)\n'
        'add_middleware(allow_origins=["*"], allow_credentials=True)\n'
    )
    diags = _check(src)
    assert len(diags) == 2
    assert [d.line for d in diags] == [1, 2]


def test_mixed_flagged_and_clean_calls():
    src = (
        'add_middleware(allow_origins=["*"], allow_credentials=False)\n'
        'add_middleware(allow_origins=["*"], allow_credentials=True)\n'
    )
    diags = _check(src)
    assert [d.line for d in diags] == [2]


# Line / column precision (reported at the Call).


def test_line_and_col_module_level():
    diags = _check('add_middleware(allow_origins=["*"], allow_credentials=True)\n')
    assert len(diags) == 1
    assert diags[0].line == 1
    assert diags[0].col == 1


def test_line_and_col_indented_call():
    src = 'def build():\n    return add_middleware(allow_origins=["*"], allow_credentials=True)\n'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].col == 12
