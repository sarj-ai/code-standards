from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_cors_wildcard_with_credentials import (
    NoCorsWildcardWithCredentials,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    if "middleware.cors import CORSMiddleware" not in source:
        source = f"from fastapi.middleware.cors import CORSMiddleware\n{source}"
    return NoCorsWildcardWithCredentials().check(Path("app.py"), source)


def _count(source: str) -> int:
    return len(_check(source))


_PUBLIC_EXAMPLES = NoCorsWildcardWithCredentials.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoCorsWildcardWithCredentials().check(Path(focus.path), focus.source)) == example.expected_count


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
    src = 'app.add_middleware(CORSMiddleware, allow_origins=["*"] if debug else allowed, allow_credentials=True)\n'
    assert _count(src) == 1


def test_flags_wildcard_bound_variable_free_list():
    src = 'app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)\n'
    assert _count(src) == 1


def test_flags_wildcard_tuple():
    src = 'app.add_middleware(CORSMiddleware, allow_origins=("*",), allow_credentials=True)\n'
    assert _count(src) == 1


def test_flags_wildcard_alongside_explicit_origins():
    src = 'app.add_middleware(CORSMiddleware, allow_origins=["https://x", "*"], allow_credentials=True)\n'
    assert _count(src) == 1


def test_flags_when_credentials_before_origins():
    """Keyword order does not matter."""
    src = 'app.add_middleware(CORSMiddleware, allow_credentials=True, allow_origins=["*"])\n'
    assert _count(src) == 1


def test_flags_nested_wildcard_deep_in_subtree():
    src = 'app.add_middleware(CORSMiddleware, allow_origins=[extra, ["*"]], allow_credentials=True)\n'
    assert _count(src) == 1


def test_message_mentions_credentials():
    diags = _check('app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)\n')
    assert len(diags) == 1
    assert "allow_credentials" in diags[0].message


def test_flags_explicit_cors_middleware_callee():
    src = 'CORSMiddleware(app, allow_origins=["*"], allow_credentials=True)\n'
    assert _count(src) == 1


@pytest.mark.parametrize("pattern", [".*", "^.*$", "(?:.*)", "(?s:.*)", r"\A.*\Z"])
def test_flags_universal_origin_regex_with_credentials(pattern: str):
    src = f'CORSMiddleware(app, allow_origin_regex=r"{pattern}", allow_credentials=True)\n'
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


def test_allows_restricted_origin_regex_with_credentials():
    src = 'CORSMiddleware(app, allow_origin_regex=r"https://.*[.]example[.]com", allow_credentials=True)\n'
    assert _check(src) == []


def test_allows_dynamic_origin_regex_with_credentials():
    src = "CORSMiddleware(app, allow_origin_regex=origin_pattern, allow_credentials=True)\n"
    assert _check(src) == []


def test_unrelated_constructor_with_cors_shaped_keywords_is_not_flagged():
    src = 'Policy(allow_origin_regex=".*", allow_credentials=True)\n'
    assert _check(src) == []


def test_locally_rebound_cors_middleware_is_not_flagged():
    src = """\
from fastapi.middleware.cors import CORSMiddleware
CORSMiddleware = Policy
CORSMiddleware(app, allow_origin_regex=".*", allow_credentials=True)
"""
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
        'app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)\n'
        'app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)\n'
    )
    diags = _check(src)
    assert len(diags) == 2
    assert [d.line for d in diags] == [2, 3]


def test_mixed_flagged_and_clean_calls():
    src = (
        'app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False)\n'
        'app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)\n'
    )
    diags = _check(src)
    assert [d.line for d in diags] == [3]


# Line / column precision (reported at the Call).


def test_line_and_col_module_level():
    diags = _check('app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)\n')
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].col == 1


def test_line_and_col_indented_call():
    src = 'def build():\n    return app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True)\n'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 3
    assert diags[0].col == 12
