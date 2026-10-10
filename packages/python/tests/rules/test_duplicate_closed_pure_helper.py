from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.duplicate_closed_pure_helper import DuplicateClosedPureHelper


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_HELPER = "def _expand(match: re.Match[str]) -> str:\n    original = match.group(0)\n    value = match.group(1)\n    separated = ' '.join(value)\n    return original.replace(value, separated)\n"
_PREFIX = "import re\nPATTERN = re.compile(r'item (\\d+)')\nOTHER = re.compile(r'code (\\d+)')\n"
_BASE = (
    _PREFIX
    + _HELPER
    + _HELPER.replace("_expand", "_separate")
    + "PATTERN.sub(_expand, text)\nOTHER.sub(_separate, text)\n"
)
_CASES = (
    EvaluationCase("closed-native-callbacks", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "immutable-pattern-fragment",
        Language.PYTHON,
        _BASE.replace("PATTERN = re.compile", "PREFIX = 'item '\nPATTERN = re.compile").replace(
            "r'item (\\d+)'", "PREFIX + r'(\\d+)'"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "distinct-domain-docstrings",
        Language.PYTHON,
        _BASE.replace("    original =", '    """Formatting chosen by the caller pattern."""\n    original =', 1),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "native-import-alias",
        Language.PYTHON,
        _BASE.replace("import re", "import re as regex").replace("re.", "regex."),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "direct-calls",
        Language.PYTHON,
        _BASE.replace("PATTERN.sub(_expand, text)", "_expand(match)").replace(
            "OTHER.sub(_separate, text)", "_separate(match)"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "different-transform",
        Language.PYTHON,
        _BASE.replace("def _separate(match", "def _separate(match").replace(
            "return original.replace(value, separated)\nPATTERN", "return separated\nPATTERN"
        ),
    ),
    EvaluationCase("custom-match-type", Language.PYTHON, _BASE.replace("re.Match[str]", "CustomMatch")),
    EvaluationCase(
        "unknown-callback-slot", Language.PYTHON, _BASE.replace("OTHER.sub(_separate, text)", "register(_separate)")
    ),
    EvaluationCase(
        "unproven-pattern",
        Language.PYTHON,
        _BASE.replace("OTHER = re.compile(r'code (\\d+)')", "OTHER = provider_pattern()"),
    ),
    EvaluationCase("mutated-pattern", Language.PYTHON, _BASE + "OTHER.sub = custom\n"),
    EvaluationCase("patched-pattern", Language.PYTHON, _BASE + "patch('examples.formatters.OTHER')\n"),
    EvaluationCase("patched-native-owner", Language.PYTHON, _BASE + "patch('re.compile')\n"),
    EvaluationCase("bytes-pattern", Language.PYTHON, _BASE.replace("r'code (\\d+)'", "rb'code (\\d+)'")),
    EvaluationCase("escaped-pattern", Language.PYTHON, _BASE + "register(OTHER)\n"),
    EvaluationCase("patched-helper", Language.PYTHON, _BASE + "patch('examples.formatters._separate')\n"),
    EvaluationCase("helper-reflection", Language.PYTHON, _BASE + "getattr(module, '_separate')\n"),
    EvaluationCase("helper-alias", Language.PYTHON, _BASE + "alias = _separate\n"),
    EvaluationCase("public-helper", Language.PYTHON, _BASE.replace("_separate", "separate")),
    EvaluationCase("decorated-helper", Language.PYTHON, _BASE.replace("def _separate", "@callback\ndef _separate")),
    EvaluationCase(
        "different-signature",
        Language.PYTHON,
        _BASE.replace("def _separate(match", "def _separate(other").replace(
            "OTHER.sub(_separate", "OTHER.sub(_separate"
        ),
    ),
    EvaluationCase("unknown-call", Language.PYTHON, _BASE.replace("' '.join(value)", "normalize(value)")),
    EvaluationCase("global-read", Language.PYTHON, _BASE.replace("' '.join(value)", "SEPARATOR.join(value)")),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase(
        "suppressed",
        Language.PYTHON,
        _BASE.replace(
            "def _separate(match: re.Match[str]) -> str:",
            "def _separate(match: re.Match[str]) -> str:  # sarj-noqa: SARJ489 -- independent release seam",
        ),
    ),
    EvaluationCase("malformed", Language.PYTHON, "def _expand(:\n"),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = DuplicateClosedPureHelper().check(Path("app/formatters.py"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len(findings) <= 1
    assert all(item.severity is Severity.WARNING for item in findings)


@pytest.mark.parametrize(
    "example",
    DuplicateClosedPureHelper.public_examples(),
    ids=tuple(example.example_id for example in DuplicateClosedPureHelper.public_examples()),
)
def test_public_examples(example: RuleExample) -> None:
    assert (
        len(DuplicateClosedPureHelper().check(Path(example.focus_path), example.focus_file.source))
        == example.expected_count
    )


def test_three_identical_helpers_emit_once_per_redundant_declaration() -> None:
    source = _BASE + _HELPER.replace("_expand", "_spread") + "PATTERN.sub(_spread, text)\n"
    rule = DuplicateClosedPureHelper()
    findings = rule.check(Path("app/formatters.py"), source)
    assert findings == rule.check(Path("app/formatters.py"), source)
    assert [item.line for item in findings] == [9, 16]
