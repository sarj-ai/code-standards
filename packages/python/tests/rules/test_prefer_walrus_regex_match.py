from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_walrus_regex_match import PreferWalrusRegexMatch


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str) -> list[Diagnostic]:
    return PreferWalrusRegexMatch().check(Path("example.py"), textwrap.dedent(source))


def test_flags_regex_search_before_if() -> None:
    source = """
    import re

    def f(text):
        m = re.search(r"\\d+", text)
        if m:
            return m.group(0)
        return None
    """
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].code == "SARJ081"
    assert "Regex match pre-assignment `m = ...` before `if`" in diags[0].message


def test_does_not_flag_non_regex_assignments() -> None:
    source = """
    def f(x):
        val = compute(x)
        if val:
            return val
        return None
    """
    diags = _check(source)
    assert len(diags) == 0


@pytest.mark.parametrize(
    "call",
    [
        pytest.param("re.match(pattern, text)", id="re-match"),
        pytest.param("regex.fullmatch(pattern, text)", id="regex-fullmatch"),
        pytest.param("pattern.search(text)", id="pattern-search"),
        pytest.param("compiled_pattern.finditer(text)", id="compiled-pattern-finditer"),
        pytest.param("parser._pattern.match(text)", id="pattern-attribute"),
    ],
)
def test_flags_supported_regex_match_calls(call: str) -> None:
    source = f"""
    result = {call}
    if result:
        consume(result)
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("import_line", "binding", "receiver"),
    [
        ("import re", 'EMAIL_RE = re.compile(r".+@.+")', "EMAIL_RE"),
        ("import re as stdlib_re", 'email_pattern = stdlib_re.compile(r".+@.+")', "email_pattern"),
        ("from re import compile as compile_regex", 'email_pattern = compile_regex(r".+@.+")', "email_pattern"),
    ],
)
def test_flags_receiver_resolved_from_re_compile_binding(import_line: str, binding: str, receiver: str) -> None:
    source = f"""
    {import_line}
    {binding}

    def validate(text):
        result = {receiver}.search(text)
        if result:
            consume(result)
    """

    assert len(_check(source)) == 1


def test_flags_local_receiver_resolved_from_re_compile_binding() -> None:
    source = """
    import re

    def validate(text):
        email_expression = re.compile(r".+@.+")
        result = email_expression.search(text)
        if result:
            consume(result)
    """

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "binding",
    [
        'email_expression = factory.compile(r".+@.+")',
        'email_expression = make_pattern(r".+@.+")',
    ],
)
def test_does_not_guess_unresolved_compiled_receivers(binding: str) -> None:
    source = f"""
    import re

    def validate(text):
        {binding}
        result = email_expression.search(text)
        if result:
            consume(result)
    """

    assert _check(source) == []


def test_does_not_resolve_a_rebound_compiled_receiver() -> None:
    source = """
    import re

    def validate(text):
        email_expression = re.compile(r".+@.+")
        email_expression = replacement
        result = email_expression.search(text)
        if result:
            consume(result)
    """

    assert _check(source) == []


def test_does_not_resolve_a_conditionally_rebound_compiled_receiver() -> None:
    source = """
    import re

    def validate(text, replacement, enabled):
        email_expression = re.compile(r".+@.+")
        if enabled:
            email_expression = replacement
        result = email_expression.search(text)
        if result:
            consume(result)
    """

    assert _check(source) == []


def test_module_compiled_receiver_shadowed_by_parameter_is_clean() -> None:
    source = """
    import re

    EMAIL_EXPRESSION = re.compile(r".+@.+")

    def validate(text, EMAIL_EXPRESSION):
        result = EMAIL_EXPRESSION.search(text)
        if result:
            consume(result)
    """

    assert _check(source) == []


def test_flags_explicit_not_none_check() -> None:
    source = """
    match = pattern.search(text)
    if match is not None:
        consume(match)
    """
    assert len(_check(source)) == 1


def test_rewritten_assignment_expression_is_clean() -> None:
    source = """
    if match := re.search(pattern, text):
        consume(match)
    """
    assert _check(source) == []


def test_requires_if_immediately_after_assignment() -> None:
    source = """
    match = re.search(pattern, text)
    record_attempt()
    if match:
        consume(match)
    """
    assert _check(source) == []


def test_keeps_assignment_when_match_is_used_after_if() -> None:
    source = """
    match = re.search(pattern, text)
    if match:
        consume(match)
    record(match)
    """
    assert _check(source) == []


def test_requires_if_to_check_assigned_name_directly() -> None:
    source = """
    match = re.search(pattern, text)
    if match and enabled:
        consume(match)
    """
    assert _check(source) == []
