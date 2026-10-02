from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.discourage_nullable_constructor_parameters import DiscourageNullableConstructorParameters


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_REJECTED = (
    "class Service:\n"
    "    def __init__(self, store: Store | None = None) -> None:\n"
    "        if store is None:\n"
    "            raise ValueError('store is required')\n"
    "        self.store = store\n"
)
_CASES = (
    EvaluationCase("rejected-default", Language.PYTHON, _REJECTED, ExpectedOutcome.MATCH),
    EvaluationCase(
        "error-message-assignment",
        Language.PYTHON,
        _REJECTED.replace(
            "raise ValueError('store is required')",
            "message = 'store is required'\n            raise ValueError(message)",
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "keyword-only-rejected-default",
        Language.PYTHON,
        _REJECTED.replace("self, store", "self, *, store"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "positional-only-rejected-default",
        Language.PYTHON,
        _REJECTED.replace("None = None)", "None = None, /)"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "reversed-none-guard",
        Language.PYTHON,
        _REJECTED.replace("store is None", "None is store"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "docstring-before-rejection",
        Language.PYTHON,
        _REJECTED.replace("        if store", '        """Construct the service."""\n        if store'),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "assert-rejected-default",
        Language.PYTHON,
        _REJECTED.replace(
            "if store is None:\n            raise ValueError('store is required')", "assert store is not None"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "nested-nullable-union",
        Language.PYTHON,
        _REJECTED.replace("Store | None", "Store | OtherStore | None"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unannotated-input",
        Language.PYTHON,
        _REJECTED.replace("store: Store | None", "store"),
    ),
    EvaluationCase(
        "nullable-container-element",
        Language.PYTHON,
        _REJECTED.replace("Store | None", "list[Store | None]"),
    ),
    EvaluationCase(
        "later-conditional-raise",
        Language.PYTHON,
        _REJECTED.replace("            raise", "            if enabled:\n                raise"),
    ),
    EvaluationCase(
        "required-nullable-input",
        Language.PYTHON,
        _REJECTED.replace(" = None", ""),
    ),
    EvaluationCase(
        "nullable-state-stored",
        Language.PYTHON,
        "class Agent:\n    def __init__(self, participant: Participant | None = None) -> None:\n        self.participant = participant\n",
    ),
    EvaluationCase(
        "absence-supported",
        Language.PYTHON,
        _REJECTED.replace("raise ValueError('store is required')", "return"),
    ),
    EvaluationCase(
        "optional-capability-guard",
        Language.PYTHON,
        _REJECTED.replace(
            "if store is None:\n            raise ValueError('store is required')",
            "if store is not None:\n            store.prepare()",
        ),
    ),
    EvaluationCase(
        "conditional-rejection",
        Language.PYTHON,
        _REJECTED.replace("if store is None", "if store is None and enabled"),
    ),
    EvaluationCase(
        "fall-back-instead-of-rejecting",
        Language.PYTHON,
        _REJECTED.replace("raise ValueError('store is required')", "store = Store()"),
    ),
    EvaluationCase(
        "rebind-before-guard",
        Language.PYTHON,
        _REJECTED.replace("        if store", "        store = resolve(store)\n        if store"),
    ),
    EvaluationCase(
        "different-rejected-input",
        Language.PYTHON,
        _REJECTED.replace("if store is None", "if other is None"),
    ),
    EvaluationCase(
        "non-none-default",
        Language.PYTHON,
        _REJECTED.replace("= None", "= DEFAULT_STORE"),
    ),
    EvaluationCase("non-nullable-input", Language.PYTHON, _REJECTED.replace("Store | None", "Store")),
    EvaluationCase("non-constructor", Language.PYTHON, _REJECTED.replace("__init__", "run")),
    EvaluationCase(
        "decorated-constructor",
        Language.PYTHON,
        _REJECTED.replace("    def __init__", "    @custom_constructor\n    def __init__"),
    ),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _REJECTED),
    EvaluationCase("malformed", Language.PYTHON, "class Service(:"),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = DiscourageNullableConstructorParameters().check(Path("app/service.py"), case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(finding.severity is Severity.WARNING for finding in findings)


def test_rejection_diagnostic_recommends_required_input_without_new_abstraction() -> None:
    finding = DiscourageNullableConstructorParameters().check(Path("app/service.py"), _REJECTED)[0]
    assert (finding.code, finding.line, finding.col) == ("SARJ468", 2, 24)
    assert "required" in finding.message
    assert "interface" not in finding.message


def test_rejected_default_is_an_actual_constructor_contract_gap() -> None:
    class Service:
        def __init__(self, store: object | None = None) -> None:
            if store is None:
                raise ValueError

    with pytest.raises(ValueError, match=r"^$"):
        Service()
    Service(object())


def test_tests_are_excluded() -> None:
    assert DiscourageNullableConstructorParameters().check(Path("tests/test_service.py"), _REJECTED) == []


@pytest.mark.parametrize("example", DiscourageNullableConstructorParameters.public_examples())
def test_public_examples(example: RuleExample) -> None:
    assert (
        len(DiscourageNullableConstructorParameters().check(Path(str(example.focus_path)), example.focus_file.source))
        == example.expected_count
    )


def test_warning_cli_and_exact_suppression(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "service.py"
    path.write_text(_REJECTED)
    assert main(["check", "--rule", DiscourageNullableConstructorParameters.id, str(path)]) == 0
    assert "SARJ468 warning:" in capsys.readouterr().out
    path.write_text(
        _REJECTED.replace(
            ") -> None:", ") -> None:  # sarj-noqa: SARJ468 -- preserve legacy constructor error semantics"
        )
    )
    assert analyze([DiscourageNullableConstructorParameters.id], [path]) == []


def test_rejected_defaults_do_not_duplicate_dependency_fallback_rules(tmp_path: Path) -> None:
    path = tmp_path / "service.py"
    path.write_text(_REJECTED)
    rules = [
        "no-hidden-constructor-fallback",
        "no-nullable-dependency-fallback",
        DiscourageNullableConstructorParameters.id,
    ]
    first = analyze(rules, [path])
    assert [finding.code for finding in first] == ["SARJ468"]
    assert first == analyze(list(reversed(rules)), [path])
    assert first == analyze(rules, [path])
