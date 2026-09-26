from pathlib import Path
import re

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.prefer_regex_fullmatch import PreferRegexFullmatch


def _guard(call: str, *, setup: str = "import re", condition: str = "not {call}") -> str:
    return f"{setup}\n\ndef validate(value):\n    if {condition.format(call=call)}:\n        raise ValueError('invalid value')\n    return value\n"


CASES = (
    EvaluationCase("direct-match", Language.PYTHON, _guard("re.match(r'^[a-z]+$', value)"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _guard("rx.match(r'^a$', value)", setup="import re as rx"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "function-alias",
        Language.PYTHON,
        _guard("match_value(r'^a$', value)", setup="from re import match as match_value"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "none-guard",
        Language.PYTHON,
        _guard("re.match(r'^a$', value)", condition="{call} is None"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("absolute-start", Language.PYTHON, _guard("re.match(r'\\Aa$', value)"), ExpectedOutcome.MATCH),
    EvaluationCase("bytes", Language.PYTHON, _guard("re.match(rb'^a$', value)"), ExpectedOutcome.MATCH),
    EvaluationCase("zero-flags", Language.PYTHON, _guard("re.match(r'^a$', value, flags=0)"), ExpectedOutcome.MATCH),
    EvaluationCase("empty-value", Language.PYTHON, _guard("re.match(r'^$', value)"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "grouped-alternation", Language.PYTHON, _guard("re.match(r'^(?:yes|no)$', value)"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "class-metacharacters", Language.PYTHON, _guard("re.match(r'^[|()$]+$', value)"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "class-negated-caret", Language.PYTHON, _guard("re.match(r'^[^^]+$', value)"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "class-initial-bracket", Language.PYTHON, _guard("re.match(r'^[]a]+$', value)"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "class-escaped-bracket", Language.PYTHON, _guard("re.match(r'^[\\]a]+$', value)"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "compiled-module",
        Language.PYTHON,
        _guard("PATTERN.match(value)", setup="import re\nPATTERN = re.compile(r'^[a-z]+$')"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "compiled-inline", Language.PYTHON, _guard("re.compile(r'^a$').match(value)"), ExpectedOutcome.MATCH
    ),
    EvaluationCase("fullmatch", Language.PYTHON, _guard("re.fullmatch(r'^a$', value)")),
    EvaluationCase("search", Language.PYTHON, _guard("re.search(r'^a$', value)")),
    EvaluationCase("prefix", Language.PYTHON, _guard("re.match(r'^a', value)")),
    EvaluationCase("unanchored-start", Language.PYTHON, _guard("re.match(r'a$', value)")),
    EvaluationCase("strict-end", Language.PYTHON, _guard("re.match(r'^a\\Z', value)")),
    EvaluationCase("escaped-dollar", Language.PYTHON, _guard("re.match(r'^a\\$', value)")),
    EvaluationCase("class-dollar", Language.PYTHON, _guard("re.match(r'^[a$]', value)")),
    EvaluationCase("top-level-alternation", Language.PYTHON, _guard("re.match(r'^yes|no$', value)")),
    EvaluationCase("multiline-flag", Language.PYTHON, _guard("re.match(r'^a$', value, re.MULTILINE)")),
    EvaluationCase("dynamic-flag", Language.PYTHON, _guard("re.match(r'^a$', value, flags=options)")),
    EvaluationCase("inline-flags", Language.PYTHON, _guard("re.match(r'(?m)^a$', value)")),
    EvaluationCase("scoped-flags", Language.PYTHON, _guard("re.match(r'^(?m:a)$', value)")),
    EvaluationCase("dynamic-pattern", Language.PYTHON, _guard("re.match(pattern, value)")),
    EvaluationCase("invalid-pattern", Language.PYTHON, _guard("re.match(r'^[z-a]$', value)")),
    EvaluationCase("invalid-parentheses", Language.PYTHON, _guard("re.match(r'^(a$', value)")),
    EvaluationCase("dollar-in-noncapturing-group", Language.PYTHON, _guard("re.match(r'^(?:a$)', value)")),
    EvaluationCase("escaped-backslash", Language.PYTHON, _guard("re.match(r'^a\\\\$', value)"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "escaped-alternation", Language.PYTHON, _guard("re.match(r'^a\\|b$', value)"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "keyword-arguments", Language.PYTHON, _guard("re.match(pattern=r'^a$', string=value)"), ExpectedOutcome.MATCH
    ),
    EvaluationCase("dynamic-arguments", Language.PYTHON, _guard("re.match(**options)")),
    EvaluationCase("other-library", Language.PYTHON, _guard("re.match(r'^a$', value)", setup="import regex as re")),
    EvaluationCase("unproven-receiver", Language.PYTHON, _guard("PATTERN.match(value)", setup="")),
    EvaluationCase("malformed-source", Language.PYTHON, "def validate(:"),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    diagnostics = PreferRegexFullmatch().check(Path("app/validation.py"), case.source)
    assert len(diagnostics) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(diagnostic.severity is Severity.WARNING for diagnostic in diagnostics)


@pytest.mark.parametrize(
    "body",
    [
        "return False",
        "record_failure()",
        "if strict:\n            raise ValueError()",
        "def reject():\n            raise ValueError()",
    ],
)
def test_only_immediate_rejection_guards(body: str) -> None:
    source = _guard("re.match(r'^a$', value)").replace("raise ValueError('invalid value')", body)
    assert not PreferRegexFullmatch().check(Path("app/validation.py"), source)


@pytest.mark.parametrize(
    "change",
    [
        "module-rebinding",
        "parameter-shadow",
        "nested-import-shadow",
        "attribute-rebinding",
        "compiled-rebinding",
        "compiled-parameter-shadow",
        "conditional-compile",
        "compiled-position",
        "compiled-escape",
        "module-escape",
        "module-alias-mutation",
        "match-capture-shadow",
    ],
)
def test_binding_and_compilation_near_misses(change: str) -> None:
    source = _guard("PATTERN.match(value)", setup="import re\nPATTERN = re.compile(r'^a$')")
    match change:
        case "module-rebinding":
            source = _guard("re.match(r'^a$', value)", setup="import re\nre = other")
        case "parameter-shadow":
            source = _guard("re.match(r'^a$', value)").replace("validate(value)", "validate(value, re)")
        case "nested-import-shadow":
            source = _guard("re.match(r'^a$', value)").replace("    if", "    import other as re\n    if")
        case "attribute-rebinding":
            source = _guard("re.match(r'^a$', value)", setup="import re\nre.match = other")
        case "compiled-rebinding":
            source += "\nPATTERN = replacement\n"
        case "compiled-parameter-shadow":
            source = source.replace("validate(value)", "validate(value, PATTERN)")
        case "conditional-compile":
            source = source.replace("PATTERN = re.compile", "if flag:\n    PATTERN = re.compile")
        case "compiled-escape":
            source += "\nconfigure(PATTERN)\n"
        case "module-escape":
            source += "\nconfigure(re)\n"
        case "module-alias-mutation":
            source += "\nalias = re\nalias.compile = other\n"
        case "match-capture-shadow":
            source = source.replace(
                "    if", "    match value:\n        case {'pattern': PATTERN}:\n            pass\n    if"
            )
        case _:
            source = source.replace("PATTERN.match(value)", "PATTERN.match(value, 1)")
    assert not PreferRegexFullmatch().check(Path("app/validation.py"), source)


def test_local_compiled_literal_and_exact_suppression() -> None:
    source = _guard("pattern.match(value)").replace("    if", "    pattern = re.compile(r'^a$')\n    if")
    findings = PreferRegexFullmatch().check(Path("app/validation.py"), source)
    assert len(findings) == 1
    suppressed = source.replace("if not pattern.match(value):", "if not pattern.match(value):  # sarj-noqa: SARJ460")
    assert not PreferRegexFullmatch().check(Path("app/validation.py"), suppressed)
    unrelated = suppressed.replace("SARJ460", "SARJ081")
    assert len(PreferRegexFullmatch().check(Path("app/validation.py"), unrelated)) == 1


@pytest.mark.parametrize("prefix", ["# @generated\n", ""])
def test_generated_and_test_files_are_excluded(prefix: str) -> None:
    path = Path("app/validation.py" if prefix else "tests/test_validation.py")
    assert not PreferRegexFullmatch().check(path, prefix + _guard("re.match(r'^a$', value)"))


def test_documentation_examples_and_no_fix_policy() -> None:
    assert PreferRegexFullmatch.documentation is not None
    assert PreferRegexFullmatch.documentation.autofix is AutofixPolicy.NONE
    for example in PreferRegexFullmatch.public_examples():
        findings = PreferRegexFullmatch().check(Path(str(example.focus_path)), example.focus_file.source)
        assert len(findings) == example.expected_count


def test_trailing_newline_is_a_real_validation_difference() -> None:
    assert re.match(r"^[a-z]+$", "valid\n") is not None
    assert re.fullmatch(r"[a-z]+", "valid\n") is None
