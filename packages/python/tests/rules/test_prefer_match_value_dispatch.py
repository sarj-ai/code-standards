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


def _siblings(first: str = "suffix in {'.yaml', '.yml'}", last: str = "suffix == '.jsonc' and valid") -> str:
    return (
        f"def parse(suffix, valid):\n    if {first}:\n        return 1\n"
        f"    if suffix == '.toml':\n        return 2\n    if {last}:\n        return 3\n    return None\n"
    )


@pytest.mark.parametrize("container", ["{'.yaml', '.yml'}", "('.yaml', '.yml')", "['.yaml', '.yml']"])
def test_grouped_terminal_dispatch(container: str) -> None:
    assert len(_check(_siblings(f"suffix in {container}"))) == 1


def test_grouped_ladder_dispatch() -> None:
    source = (
        _siblings()
        .replace("    if suffix ==", "    elif suffix ==")
        .replace("    return None", "    else:\n        return None")
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "first",
    [
        "suffix in ()",
        "suffix in ('.yaml',)",
        "suffix in OPTIONS",
        "suffix in (*OPTIONS, '.yml')",
        "suffix in {True, None}",
        "suffix in {'.yaml', '.toml'}",
        "suffix in {'.yaml', '.yaml'}",
        "suffix == '.yaml' or suffix == '.yml'",
        "other in {'.yaml', '.yml'}",
        "suffix in ('a', 'b', 'c', 'd', 'e', 'f', 'g')",
        "ready and suffix == '.yaml'",
    ],
)
def test_grouped_dispatch_near_misses(first: str) -> None:
    assert _check(_siblings(first)) == []


@pytest.mark.parametrize(
    "last", ["valid and suffix == '.jsonc'", "suffix == '.jsonc' or valid", "suffix == '.jsonc' and (valid := check())"]
)
def test_unsafe_final_guards(last: str) -> None:
    assert _check(_siblings(last=last)) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("return 1", "run()"),
        ("return 2", "return 1"),
        ("    return None\n", ""),
        ("    if suffix == '.toml':", "    suffix = update()\n    if suffix == '.toml':"),
        ("suffix", "path.suffix"),
    ],
)
def test_terminal_dispatch_boundaries(old: str, new: str) -> None:
    assert _check(_siblings().replace(old, new)) == []


def test_mixed_predicates_with_identical_returns_are_not_dispatch() -> None:
    assert (
        _check(
            "def stop(stripped, suffix, line, indent):\n    if not stripped or (suffix in {'.yaml', '.yml'} and stripped in {'---', '...'}):\n        return True\n    if suffix == '.toml' and valid(stripped):\n        return True\n    if comment(line) is None and len(line) < indent:\n        return True\n    return False\n"
        )
        == []
    )


def test_terminal_dispatch_keeps_try_except_body() -> None:
    source = _siblings().replace(
        "        return 1",
        "        try:\n            validate()\n        except ValueError:\n            return None\n        return 1",
    )
    assert len(_check(source)) == 1


def test_mixed_sibling_sequence_has_no_eligible_suffix() -> None:
    assert _check(_siblings().replace("    if suffix in", "    if ready:\n        return 0\n    if suffix in")) == []


def test_membership_and_pattern_matching_are_not_safe_automatic_rewrites() -> None:
    class UnhashableEqual:
        def __hash__(self) -> int:
            raise TypeError

        def __eq__(self, other: object) -> bool:
            return other == ".yaml"

    def make_value() -> object:
        return UnhashableEqual()

    value = make_value()
    with pytest.raises(TypeError):
        _ = value in {".yaml", ".yml"}
    match value:
        case ".yaml" | ".yml":
            matched = True
        case _:
            matched = False
    assert matched


def test_set_membership_invokes_hash_but_literal_pattern_does_not() -> None:
    calls: list[str] = []

    class HashObserved:
        def __hash__(self) -> int:
            calls.append("hash")
            return hash(".yaml")

        def __eq__(self, other: object) -> bool:
            calls.append("eq")
            return other == ".yaml"

    def make_value() -> object:
        return HashObserved()

    value = make_value()
    assert value in {".yaml", ".yml"}
    assert "hash" in calls
    calls.clear()
    match value:
        case ".yaml" | ".yml":
            matched = True
        case _:
            matched = False
    assert matched
    assert calls == ["eq"]


def test_two_separate_terminal_sequences_have_one_finding_each() -> None:
    assert len(_check(_siblings() + _siblings().replace("def parse", "def other"))) == 2


def test_expanded_mixed_ladder_has_no_eligible_suffix() -> None:
    source = (
        _siblings()
        .replace("    if suffix ==", "    elif suffix ==")
        .replace("    return None", "    else:\n        return None")
    )
    source = source.replace("    if suffix in", "    if ready:\n        return 0\n    elif suffix in")
    assert _check(source) == []


def test_exact_parser_dispatch_shape() -> None:
    source = """
def literal_lines(path, source, lines):
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            list(yaml.compose_all(source))
        except yaml.YAMLError:
            return None
        return _config_literal_lines(path, lines)
    if suffix == ".toml":
        try:
            tomllib.loads(source)
        except tomllib.TOMLDecodeError:
            return None
        return _config_literal_lines(path, lines)
    if suffix == ".jsonc" and _structured_config_document(suffix, source) is not None:
        return set()
    return None
"""
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].line == 4


def test_terminal_raise_dispatch() -> None:
    assert (
        len(_check(_siblings().replace("return 1", "raise FirstError").replace("return None", "raise Unsupported")))
        == 1
    )


def test_two_terminal_siblings_remain_below_expansion_threshold() -> None:
    assert (
        _check(
            "def parse(value):\n    if value == 'a':\n        return 1\n    if value == 'b':\n        return 2\n    return None\n"
        )
        == []
    )


def test_warning_rule_has_no_automatic_fix() -> None:
    assert PreferMatchValueDispatch.documentation is not None
    assert PreferMatchValueDispatch.documentation.autofix.value == "none"


def test_with_suppressed_raise_is_not_a_terminal_branch() -> None:
    source = _siblings().replace("        return 1", "        with suppress(Exception):\n            raise FirstError")
    assert _check(source) == []


def test_three_plain_equality_terminal_siblings_are_supported() -> None:
    assert len(_check(_siblings("suffix == '.yaml'", "suffix == '.jsonc'"))) == 1


def test_numeric_module_constant_overlap_is_excluded_in_siblings() -> None:
    source = "FIRST = 1\nSECOND = 1.0\n" + _siblings("suffix == FIRST", "suffix == SECOND")
    assert _check(source) == []
