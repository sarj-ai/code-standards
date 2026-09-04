from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

import sarj_python_lint.rules.prefer_walrus_regex_match as rule_module
from sarj_python_lint.rules.prefer_walrus_regex_match import PreferWalrusRegexMatch


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str) -> list[Diagnostic]:
    return PreferWalrusRegexMatch().check(Path("example.py"), textwrap.dedent(source))


_PUBLIC_EXAMPLES = PreferWalrusRegexMatch.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferWalrusRegexMatch().check(Path(focus.path), focus.source)) == example.expected_count


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
    assert "Regex result `m` is assigned only for the following condition" in diags[0].message


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
    ("import_line", "call"),
    [
        pytest.param("import re", "re.match(pattern, text)", id="re-match"),
        pytest.param("import re as regex_engine", "regex_engine.fullmatch(pattern, text)", id="re-alias"),
        pytest.param("import regex", "regex.search(pattern, text)", id="regex-module"),
    ],
)
def test_flags_import_proven_regex_match_calls(import_line: str, call: str) -> None:
    source = f"""
    {import_line}
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
    import re

    match = re.search(pattern, text)
    if match is not None:
        consume(match)
    """
    assert len(_check(source)) == 1


def test_flags_parameter_annotated_as_stdlib_pattern() -> None:
    source = """
    import re

    def parse(pattern: re.Pattern[str], text: str) -> str | None:
        match = pattern.search(text)
        if match:
            return match.group(0)
        return None
    """
    assert len(_check(source)) == 1


def test_flags_function_local_module_alias() -> None:
    source = """
    def parse(text):
        import re as regex_engine
        match = regex_engine.search(r"x", text)
        if match:
            return match.group(0)
        return None
    """
    assert len(_check(source)) == 1


def test_flags_inside_module_suite_after_the_import() -> None:
    source = """
    import re

    if enabled:
        match = re.search(r"x", text)
        if match:
            consume(match)
    """
    assert len(_check(source)) == 1


def test_does_not_use_a_later_module_import_inside_a_suite() -> None:
    source = """
    if enabled:
        match = re.search(r"x", text)
        if match:
            consume(match)

    import re
    """
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(
            "def parse(pattern, text):\n    match = pattern.search(text)\n    if match:\n        return match\n",
            id="arbitrary-parameter",
        ),
        pytest.param(
            "def parse(parser, text):\n    match = parser._pattern.search(text)\n    if match:\n        return match\n",
            id="arbitrary-attribute",
        ),
        pytest.param(
            "def parse(re, text):\n    match = re.search(r'x', text)\n    if match:\n        return match\n",
            id="shadowed-module",
        ),
        pytest.param(
            "import re\nre = Client()\nmatch = re.search('x', text)\nif match:\n    consume(match)\n",
            id="rebound-module",
        ),
        pytest.param(
            "import re\nitems = re.finditer('x', text)\nif items:\n    consume(items)\n",
            id="always-truthy-finditer",
        ),
        pytest.param(
            "import re\nmatch = pattern.search(text)\nif match:\n    consume(match)\npattern = re.compile('x')\n",
            id="compile-binding-after-use",
        ),
    ],
)
def test_does_not_guess_regex_provenance(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "separator",
    [pytest.param("\n", id="blank-line"), pytest.param("# Keep the operation named.\n", id="comment")],
)
def test_requires_physical_adjacency(separator: str) -> None:
    source = f"import re\nmatch = re.search('x', text)\n{separator}if match:\n    consume(match)\n"
    assert _check(source) == []


def test_skips_multiline_assignment() -> None:
    source = """
    import re
    match = re.search(
        very_long_pattern,
        text,
    )
    if match:
        consume(match)
    """
    assert _check(source) == []


def test_skips_a_long_single_line_rewrite() -> None:
    pattern = "x" * 90
    source = f"import re\nmatch = re.search('{pattern}', text)\nif match:\n    consume(match)\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    ("path", "source"),
    [
        (Path("test_parser.py"), "import re\nmatch = re.search('x', text)\nif match:\n    consume(match)\n"),
        (
            Path("generated_parser.py"),
            "# @generated\nimport re\nmatch = re.search('x', text)\nif match:\n    consume(match)\n",
        ),
    ],
)
def test_excludes_tests_and_generated_files(path: Path, source: str) -> None:
    assert PreferWalrusRegexMatch().check(path, source) == []


def test_lexical_gate_avoids_parsing_unrelated_source(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_parse(_path: Path, _source: str) -> None:
        pytest.fail("parse_or_none should not run")

    monkeypatch.setattr(rule_module, "parse_or_none", fail_parse)
    assert _check("def value() -> int:\n    return 1\n") == []


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
