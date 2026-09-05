from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.prefer_match_value_dispatch import PreferMatchValueDispatch


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/dispatch.py") -> list[Diagnostic]:
    return PreferMatchValueDispatch().check(Path(path), source)


def _ladder(first: str = "value == 'a'", second: str = "value == 'b'") -> str:
    return f"if {first}:\n    result = first()\nelif {second}:\n    result = second()\nelse:\n    result = fallback()\n"


_EXAMPLES = PreferMatchValueDispatch.public_examples()


@pytest.mark.parametrize("example", _EXAMPLES, ids=tuple(example.example_id for example in _EXAMPLES))
def test_documentation_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, str(example.focus_path))) == example.expected_count


def test_two_tests_and_fallback_are_a_warning() -> None:
    diagnostics = _check(_ladder())
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ439"
    assert diagnostics[0].severity.value == "warning"
    assert diagnostics[0].line == 1
    assert diagnostics[0].col == 1
    assert "attribute evaluation" in diagnostics[0].message


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("path.name == 'a'", "path.name == 'b'"),
        ("request.path.name == 'a'", "request.path.name == 'b'"),
        ("value == -1", "value == +2"),
        ("value == b'a'", "value == b'b'"),
        ("value == 1.5", "value == 2.5"),
    ],
)
def test_supported_values_and_subjects(first: str, second: str) -> None:
    assert len(_check(_ladder(first, second))) == 1


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("value == 'a'", "value == 'a'"),
        ("value == 1", "value == 1.0"),
        ("value == -0", "value == 0"),
        ("value == True", "value == False"),
        ("value == -True", "value == 1"),
        ("value == None", "value == 'b'"),
        ("get_value() == 'a'", "get_value() == 'b'"),
        ("get_value().name == 'a'", "get_value().name == 'b'"),
        ("value[0] == 'a'", "value[0] == 'b'"),
        ("value == 'a'", "other == 'b'"),
        ("value == 'a'", "'b' == value"),
        ("'a' == value", "'b' == value"),
        ("value != 'a'", "value == 'b'"),
        ("value is None", "value == 'b'"),
        ("value == 'a' and ready", "value == 'b'"),
        ("value == 'a'", "value == make_case()"),
        ("value == 'a'", "value == UNKNOWN"),
        ("value == 'a'", "value == constants.B"),
        ("value == 'a' == other", "value == 'b'"),
    ],
)
def test_unsafe_or_unrelated_tests_are_excluded(first: str, second: str) -> None:
    assert _check(_ladder(first, second)) == []


def test_resolves_literal_module_constants() -> None:
    assert len(_check("FIRST: str = 'a'\nSECOND = 'b'\n" + _ladder("value == FIRST", "value == SECOND"))) == 1


@pytest.mark.parametrize(
    "binding",
    [
        "FIRST = 'c'",
        "FIRST += 'c'",
        "del FIRST",
        "import FIRST",
        "from other import FIRST",
        "from other import *",
        "def other(FIRST): pass",
        "def other[FIRST](): pass",
        "def FIRST(): pass",
        "class FIRST: pass",
        "for FIRST in items: pass",
        "with context() as FIRST: pass",
        "if ready: FIRST = 'c'",
        "if (FIRST := 'c'): pass",
        "def other():\n    global FIRST",
        "try:\n    run()\nexcept Error as FIRST:\n    pass",
        "match data:\n    case FIRST:\n        pass",
        "match data:\n    case [*FIRST]:\n        pass",
        "match data:\n    case {'a': entry, **FIRST}:\n        pass",
    ],
)
def test_ambiguous_constant_bindings_are_excluded(binding: str) -> None:
    source = "FIRST = 'a'\nSECOND = 'b'\n" + binding + "\n" + _ladder("value == FIRST", "value == SECOND")
    assert _check(source) == []


def test_duplicate_named_values_are_excluded() -> None:
    assert _check("FIRST = 'a'\nSECOND = 'a'\n" + _ladder("value == FIRST", "value == SECOND")) == []


def test_identical_bodies_defer_to_ruff_sim114() -> None:
    assert _check(_ladder().replace("result = second()", "result = first()")) == []


def test_annotated_path_sample_is_advisory() -> None:
    source = """
from pathlib import Path
_ESLINT_SUPPRESSIONS = 'eslint.json'
_RATCHET_SUPPRESSIONS = 'ratchet.json'
def migrate(path: Path, original, eslint, codes):
    if path.name == _ESLINT_SUPPRESSIONS:
        migrated = _rewrite_eslint_suppressions(original, eslint)
    elif path.name == _RATCHET_SUPPRESSIONS:
        migrated = _rewrite_ratchet_suppressions(original, codes)
    else:
        migrated = _rewrite(path, original, eslint, codes)
    return migrated
"""
    assert len(_check(source)) == 1


def test_missing_fallback_is_excluded() -> None:
    assert _check("if value == 'a':\n    first()\nelif value == 'b':\n    second()\n") == []


def test_single_test_is_excluded() -> None:
    assert _check("if value == 'a':\n    first()\nelse:\n    fallback()\n") == []


def test_else_nested_if_is_not_elif() -> None:
    assert (
        _check(
            "if value == 'a':\n    first()\nelse:\n    if value == 'b':\n        second()\n    else:\n        fallback()\n"
        )
        == []
    )


def test_reports_maximal_chain_once() -> None:
    source = _ladder().replace("else:\n", "elif value == 'c':\n    third()\nelse:\n")
    assert len(_check(source)) == 1


def test_does_not_report_eligible_suffix_of_mixed_chain() -> None:
    source = "if ready:\n    prepare()\nel" + _ladder()
    assert _check(source) == []


def test_multiline_test_is_supported() -> None:
    assert len(_check(_ladder().replace("elif value == 'b':", "elif (\n    value == 'b'\n):"))) == 1


@pytest.mark.parametrize("source", ["if:", "# Generated file; do not edit\n" + _ladder()])
def test_invalid_and_generated_sources_are_excluded(source: str) -> None:
    assert _check(source) == []
