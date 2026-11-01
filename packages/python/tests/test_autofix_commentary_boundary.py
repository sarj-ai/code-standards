from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest
from sarj_rule_contracts import apply_edits

from sarj_python_lint._autofix_comments import CommentFixes
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rule_base import Diagnostic, Severity
from sarj_python_lint.rules import REGISTRY


_RULE = "excessive-commentary"
_PATH = Path("app/service.py")
_SUBJECTS = ("account", "endpoint", "profile", "action")


def _paragraph(kind: str) -> str:
    actions = [f"Collect {subject} activation rejection reasons" for subject in _SUBJECTS]
    match kind:
        case "rationale":
            sentences = [f"Must keep {subject} activation security checks ordered" for subject in _SUBJECTS]
        case "technical":
            sentences = [
                f"Collect {subject}Profile activation rejection reasons before dispatch" for subject in _SUBJECTS
            ]
        case _:
            sentences = [f"Collect {subject} activation rejection reasons under RFC 9110" for subject in _SUBJECTS]
    comments = "".join(f"    # {sentence}\n" for sentence in sentences)
    calls = "".join(f"    values.extend({'_'.join(action.casefold().split())}())\n" for action in actions)
    return f"def reasons():\n{comments}    values = []\n{calls}    return values\n"


@pytest.mark.parametrize("kind", ["rationale", "technical", "citation"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=("lf", "crlf"))
def test_meaning_beyond_action_names_preserves_the_comments(kind: str, newline: str) -> None:
    source = _paragraph(kind).replace("\n", newline)
    findings = REGISTRY[_RULE]().check(_PATH, source)
    assert findings == []
    context = PythonFileContext(_PATH, source)
    forced_error = Diagnostic(_PATH, 2, 5, "SARJ434", "duplicate narration", severity=Severity.ERROR)
    assert CommentFixes(context).fixes(forced_error) == []
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source
    assert fix_source(_PATH, source, rule_ids=[]) == source


def test_warning_diagnostic_refuses_the_otherwise_safe_shape() -> None:
    documentation = REGISTRY[_RULE].documentation
    assert documentation is not None
    example = next(item for item in documentation.examples if item.example_id == "safe-autofix-subset")
    source = example.focus_file.source
    finding = REGISTRY[_RULE]().check(_PATH, source)[0]
    assert finding.severity is Severity.ERROR
    assert CommentFixes(PythonFileContext(_PATH, source)).fixes(replace(finding, severity=Severity.WARNING)) == []


def test_off_severity_cannot_be_emitted_as_a_diagnostic() -> None:
    finding = Diagnostic(_PATH, 1, 1, "SARJ434", "duplicate narration")
    with pytest.raises(ValueError, match="native diagnostic severity must be error or warning"):
        replace(finding, severity=Severity.OFF)


def test_original_error_fix_still_converges_beside_preserved_technical_prose() -> None:
    documentation = REGISTRY[_RULE].documentation
    assert documentation is not None
    example = next(item for item in documentation.examples if item.example_id == "safe-autofix-subset")
    warning = _paragraph("rationale").replace("def reasons():", "def guarded_reasons():")
    source = example.focus_file.source + "\n" + warning
    findings = REGISTRY[_RULE]().check(_PATH, source)
    assert [finding.severity for finding in findings] == [Severity.ERROR]
    fixed = fix_source(_PATH, source, rule_ids=[_RULE])
    assert fixed == example.fixed_files[0].source + "\n" + warning
    assert ast.dump(ast.parse(fixed), include_attributes=True) == ast.dump(ast.parse(source), include_attributes=True)
    assert (
        compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
            fixed, str(_PATH), "exec", dont_inherit=True
        )
        == compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
            source, str(_PATH), "exec", dont_inherit=True
        )
    )
    assert REGISTRY[_RULE]().check(_PATH, fixed) == []
    assert fix_source(_PATH, fixed, rule_ids=[_RULE]) == fixed


_TEST_RULE = "no-test-comments"
_TEST_PATH = Path("tests/test_activation.py")
_TEST_SOURCE = (
    "def test_activation():\n"
    "    # Load current account profile activation settings\n"
    "    # Build current account profile activation response\n"
    "    load_current_account_profile_activation_settings()\n"
    "    return build_current_account_profile_activation_response()\n"
)
_TEST_FIXED = (
    "def test_activation():\n\n\n"
    "    load_current_account_profile_activation_settings()\n"
    "    return build_current_account_profile_activation_response()\n"
)


@pytest.mark.parametrize(
    "selected",
    [
        pytest.param([_TEST_RULE], id="test-comment-owner"),
        pytest.param([_RULE], id="narration-owner"),
        pytest.param([_TEST_RULE, _RULE], id="both-owners"),
    ],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=("lf", "crlf"))
def test_test_comment_fix_reuses_the_exact_narration_proof(selected: list[str], newline: str) -> None:
    source, expected = (text.replace("\n", newline) for text in (_TEST_SOURCE, _TEST_FIXED))
    actual = fix_source(_TEST_PATH, source, rule_ids=selected)
    assert actual == expected
    assert ast.dump(ast.parse(actual), include_attributes=True) == ast.dump(ast.parse(source), include_attributes=True)
    assert (
        compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
            actual, str(_TEST_PATH), "exec", dont_inherit=True
        )
        == compile(  # sarj-noqa: SARJ557 -- Compile reviewed fixtures to validate compiler behavior and transformation equivalence.
            source, str(_TEST_PATH), "exec", dont_inherit=True
        )
    )
    assert REGISTRY[_TEST_RULE]().check(_TEST_PATH, actual) == []
    assert fix_source(_TEST_PATH, actual, rule_ids=[_TEST_RULE]) == actual
    assert fix_source(_TEST_PATH, actual, rule_ids=selected) == actual


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=("lf", "crlf"))
def test_test_comment_fix_keeps_empty_selection(newline: str) -> None:
    source = _TEST_SOURCE.replace("\n", newline)
    assert len(REGISTRY[_TEST_RULE]().check(_TEST_PATH, source)) == 2
    assert fix_source(_TEST_PATH, source, rule_ids=[]) == source


@pytest.mark.parametrize(
    "locations",
    [pytest.param(frozenset[tuple[int, int]](), id="no-owner"), pytest.param(frozenset({(2, 5)}), id="partial-owner")],
)
def test_test_comment_fix_requires_ownership_of_every_removed_line(locations: frozenset[tuple[int, int]]) -> None:
    context = PythonFileContext(_TEST_PATH, _TEST_SOURCE)
    finding = REGISTRY[_TEST_RULE]().check_context(context)[0]
    assert CommentFixes(context, test_comment_locations=locations).fixes(finding) == []


def test_owned_test_comments_use_the_existing_writer_without_changing_severity() -> None:
    context = PythonFileContext(_TEST_PATH, _TEST_SOURCE)
    findings = REGISTRY[_TEST_RULE]().check_context(context)
    locations = frozenset((finding.line, finding.col) for finding in findings)
    assert all(finding.severity is Severity.WARNING for finding in findings)
    edits = CommentFixes(context, test_comment_locations=locations).fixes(findings[0])
    assert apply_edits(_TEST_SOURCE, edits) == _TEST_FIXED


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(_TEST_SOURCE.replace("settings\n", "settings because compatibility matters\n"), id="rationale"),
        pytest.param(_TEST_SOURCE.replace("settings\n", "settings under RFC 9110\n"), id="citation"),
        pytest.param(_TEST_SOURCE.replace("profile activation settings", "profileActivation settings"), id="technical"),
        pytest.param(_TEST_SOURCE.replace("    # Load", "    # Copyright 2026 Example\n    # Load"), id="legal-run"),
        pytest.param(_TEST_SOURCE.replace("    # Load", "    # pyright: strict\n    # Load"), id="tool-directive"),
        pytest.param(
            _TEST_SOURCE.replace("settings\n", "settings  # sarj-noqa: SARJ551 -- retained authored contract\n"),
            id="suppressed-line",
        ),
        pytest.param(_TEST_SOURCE.replace("    load_current", "    observe()\n    load_current"), id="extra-statement"),
        pytest.param("# Generated by protoc. Do not edit.\n" + _TEST_SOURCE, id="generated"),
    ],
)
def test_test_comment_fix_retains_unproved_or_unowned_prose(source: str) -> None:
    assert fix_source(_TEST_PATH, source, rule_ids=[_TEST_RULE]) == source


def test_test_comment_fix_does_not_claim_production_comment_ownership() -> None:
    assert REGISTRY[_TEST_RULE]().check(_PATH, _TEST_SOURCE) == []
    assert fix_source(_PATH, _TEST_SOURCE, rule_ids=[_TEST_RULE]) == _TEST_SOURCE
