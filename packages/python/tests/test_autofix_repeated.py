from __future__ import annotations

import ast
from pathlib import Path
from types import CodeType, FunctionType
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from collections.abc import Callable


_RULE = "no-repeated-structured-string-literal"
_PATH = Path("app/queries.py")
_LITERAL = "SELECT id, name, created_at FROM organization"


def _source() -> str:
    documentation = REGISTRY[_RULE].documentation
    assert documentation is not None
    return next(example.focus_file.source for example in documentation.examples if example.fixed_files)


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=("lf", "crlf"))
@pytest.mark.parametrize("final_newline", [True, False], ids=("newline", "eof"))
def test_whole_length_only_group_reuses_the_authored_local_binding(newline: str, *, final_newline: bool) -> None:
    source = _source()
    expected = source.replace(f"len({_LITERAL!r})", "len(query)")
    if not final_newline:
        source = source.removesuffix("\n")
        expected = expected.removesuffix("\n")
    source = source.replace("\n", newline)
    expected = expected.replace("\n", newline)
    assert len(REGISTRY[_RULE]().check(_PATH, source)) == 2
    fixed = fix_source(_PATH, source, rule_ids=[_RULE])
    assert fixed == expected
    assert not REGISTRY[_RULE]().check(_PATH, fixed)
    assert fix_source(_PATH, fixed, rule_ids=[_RULE]) == fixed
    assert fix_source(_PATH, source, rule_ids=[]) == source
    assert _result(source) == _result(fixed) == (len(_LITERAL),) * 3


def _result(source: str) -> object:
    code = compile(source, str(_PATH), "exec", dont_inherit=True)
    constants: tuple[object, ...] = code.co_consts
    function = next(value for value in constants if isinstance(value, CodeType) and value.co_name == "length_contracts")
    return _invoke(FunctionType(function, {}))


def _invoke(function: Callable[[], object]) -> object:
    return function()


@pytest.mark.parametrize("identifier", ["sql_query", "查询", "ｑｕｅｒｙ"])
def test_original_binding_spelling_is_retained(identifier: str) -> None:
    source = _source().replace("query", identifier)
    expected = source.replace(f"len({_LITERAL!r})", f"len({identifier})")
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == expected
    assert _result(source) == _result(expected)


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=("lf", "crlf"))
def test_multiline_literal_replacement_retains_all_following_line_numbers(newline: str) -> None:
    literal = "SELECT id, name,\ncreated_at FROM organization"
    source = _source().replace(repr(_LITERAL), repr(literal), 1)
    source = source.replace(repr(_LITERAL), "'''" + literal + "'''").replace("\n", newline)
    fixed = fix_source(_PATH, source, rule_ids=[_RULE])
    assert fixed != source
    assert source.count(newline) == fixed.count(newline)
    assert _result(source) == _result(fixed) == (len(literal),) * 3
    assert not REGISTRY[_RULE]().check(_PATH, fixed)
    before = ast.parse(source).body[0]
    after = ast.parse(fixed).body[0]
    assert isinstance(before, ast.FunctionDef)
    assert isinstance(after, ast.FunctionDef)
    assert ast.dump(before.body[-1], include_attributes=True) == ast.dump(after.body[-1], include_attributes=True)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("    def _canonical():\n        return len(query)\n", ""),
        ("    def _canonical():", "    def canonical():"),
        ("    def _canonical():", "    def _canonical[query]():"),
        ("_canonical()", "canonical()"),
        ("    def _first():", "    query = 'different value'\n    def _first():"),
        ("    def _first():", f"    other_query = {_LITERAL!r}\n    def _first():"),
        ("    query =", "    if True:\n        query ="),
        (
            "    def _first():",
            "    def _first(query='shadow'):",
        ),
        ("def length_contracts():", "def length_contracts[len]():"),
        ("def length_contracts():", "def length_contracts[query]():"),
        ("def length_contracts():", "def length_contracts(len):"),
        ("    def _first():", "    def _first[len]():"),
        (f"        return len({_LITERAL!r})", f"        return {_LITERAL!r}"),
        (f"len({_LITERAL!r})", f"len({_LITERAL!r}, extra=True)"),
        ("    return (_canonical()", "    observe()\n    return (_canonical()"),
        ("    return (_canonical(), _first(), _second())", "    return _first"),
        ("    return (_canonical()", "    yield (_canonical()"),
        ("def length_contracts():", "async def length_contracts():"),
        ("    def _first():", "    # Preserve the ownership boundary.\n    def _first():"),
        ("    def _first():", "    def _first():\n        nonlocal query"),
        ("    def _first():", "    def _first():\n        global query"),
        ("    def _first():", "    def _first():\n        locals()"),
        ("    def _first():", "    def _first():\n        raise ValueError('stop')"),
    ],
    ids=(
        "no-existing-shared-read",
        "public-canonical-helper",
        "canonical-helper-type-parameter",
        "unbound-canonical-call",
        "reassigned-binding",
        "competing-binding",
        "conditional-binding",
        "local-shadow",
        "parent-len-type-parameter",
        "parent-binding-type-parameter",
        "parent-len-parameter",
        "helper-len-type-parameter",
        "string-identity-escapes",
        "noncanonical-len-signature",
        "external-callout",
        "helper-escapes",
        "parent-generator",
        "parent-coroutine",
        "ownership-comment",
        "nonlocal-binding",
        "global-binding",
        "namespace-observer",
        "traceback-escape",
    ),
)
def test_unproven_binding_or_group_remains_manual(old: str, new: str) -> None:
    source = _source().replace(old, new)
    assert REGISTRY[_RULE]().check(_PATH, source)
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


def test_one_non_length_copy_prevents_partial_group_rewriting() -> None:
    source = _source().replace(
        "    return (_canonical()",
        f"    def _third():\n        return {_LITERAL!r}\n    return (_canonical()",
    )
    assert len(REGISTRY[_RULE]().check(_PATH, source)) == 3
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


def test_module_constant_identity_does_not_replace_a_local_literal() -> None:
    source = f"QUERY = {_LITERAL!r}\n" + _source()
    assert len(REGISTRY[_RULE]().check(_PATH, source)) == 3
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source


def test_suppressed_member_preserves_the_entire_repeated_group() -> None:
    source = _source().replace(
        f"return len({_LITERAL!r})", f"return len({_LITERAL!r})  # sarj-noqa: SARJ024 -- independent ownership", 1
    )
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source
