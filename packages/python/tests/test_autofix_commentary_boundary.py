from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from sarj_python_lint._autofix_comments import CommentFixes
from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.autofix import fix_source
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules import REGISTRY


_RULE = "excessive-commentary"
_PATH = Path("app/service.py")
_SUBJECTS = ("account", "endpoint", "profile", "action")


def _paragraph(kind: str) -> str:
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
    calls = "".join(f"    values.extend({'_'.join(sentence.casefold().split())}())\n" for sentence in sentences)
    return f"def reasons():\n{comments}    values = []\n{calls}    return values\n"


@pytest.mark.parametrize("kind", ["rationale", "technical", "citation"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=("lf", "crlf"))
def test_expanded_commentary_warnings_preserve_their_comments(kind: str, newline: str) -> None:
    source = _paragraph(kind).replace("\n", newline)
    findings = REGISTRY[_RULE]().check(_PATH, source)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    context = PythonFileContext(_PATH, source)
    assert CommentFixes(context).fixes(findings[0]) == []
    # The first two are exact authored-word accumulator shapes. Only the new
    # severity boundary prevents deletion; citation syntax already fails the
    # existing plain-word proof and must remain refused independently.
    forced_error = CommentFixes(context).fixes(replace(findings[0], severity=Severity.ERROR))
    assert bool(forced_error) is (kind != "citation")
    assert fix_source(_PATH, source, rule_ids=[_RULE]) == source
    assert fix_source(_PATH, source, rule_ids=[]) == source


@pytest.mark.parametrize("severity", [Severity.WARNING, Severity.OFF])
def test_any_nonerror_diagnostic_refuses_the_otherwise_safe_shape(severity: Severity) -> None:
    documentation = REGISTRY[_RULE].documentation
    assert documentation is not None
    example = next(item for item in documentation.examples if item.example_id == "safe-autofix-subset")
    source = example.focus_file.source
    finding = REGISTRY[_RULE]().check(_PATH, source)[0]
    assert finding.severity is Severity.ERROR
    assert CommentFixes(PythonFileContext(_PATH, source)).fixes(replace(finding, severity=severity)) == []


def test_original_error_fix_still_converges_beside_an_unfixed_warning() -> None:
    documentation = REGISTRY[_RULE].documentation
    assert documentation is not None
    example = next(item for item in documentation.examples if item.example_id == "safe-autofix-subset")
    warning = _paragraph("rationale").replace("def reasons():", "def guarded_reasons():")
    source = example.focus_file.source + "\n" + warning
    findings = REGISTRY[_RULE]().check(_PATH, source)
    assert [finding.severity for finding in findings] == [Severity.ERROR, Severity.WARNING]
    fixed = fix_source(_PATH, source, rule_ids=[_RULE])
    assert fixed == example.fixed_files[0].source + "\n" + warning
    assert ast.dump(ast.parse(fixed), include_attributes=True) == ast.dump(ast.parse(source), include_attributes=True)
    assert compile(fixed, str(_PATH), "exec", dont_inherit=True) == compile(
        source, str(_PATH), "exec", dont_inherit=True
    )
    assert [finding.severity for finding in REGISTRY[_RULE]().check(_PATH, fixed)] == [Severity.WARNING]
    assert fix_source(_PATH, fixed, rule_ids=[_RULE]) == fixed
