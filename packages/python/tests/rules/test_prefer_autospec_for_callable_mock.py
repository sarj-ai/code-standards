from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock, create_autospec  # ruff: ignore[banned-api] -- reproduce SARJ474's signature gap

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.prefer_autospec_for_callable_mock import PreferAutospecForCallableMock


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


_BASE = (
    "from unittest.mock import Mock\n"
    "def send(*, recipient: str) -> None:\n    pass\n"
    "def test_send():\n    double = Mock(spec=send)\n    double(recipient='sample')\n"
)
_CASES = (
    EvaluationCase("fixed-keyword", Language.PYTHON, _BASE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "mock-autospec-keyword-is-not-autospec",
        Language.PYTHON,
        _BASE.replace("spec=send", "spec=send, autospec=True"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("magic-mock", Language.PYTHON, _BASE.replace("Mock", "MagicMock"), ExpectedOutcome.MATCH),
    EvaluationCase("async-mock-sync-spec", Language.PYTHON, _BASE.replace("Mock", "AsyncMock")),
    EvaluationCase(
        "async-mock-async-spec-awaited",
        Language.PYTHON,
        _BASE.replace("Mock", "AsyncMock")
        .replace("def send", "async def send")
        .replace("def test_send", "async def test_send")
        .replace("    double(recipient=", "    await double(recipient="),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("spec-set", Language.PYTHON, _BASE.replace("spec=", "spec_set="), ExpectedOutcome.MATCH),
    EvaluationCase(
        "async-function", Language.PYTHON, _BASE.replace("def send", "async def send"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "constructor-alias",
        Language.PYTHON,
        _BASE.replace("import Mock", "import Mock as Double").replace("= Mock(", "= Double("),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "module-alias",
        Language.PYTHON,
        _BASE.replace("from unittest.mock import Mock", "import unittest.mock as doubles").replace(
            "= Mock(", "= doubles.Mock("
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "annotated-binding", Language.PYTHON, _BASE.replace("double =", "double: object ="), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "configured-result",
        Language.PYTHON,
        _BASE.replace("spec=send", "spec=send, return_value=None"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "repeat-calls-one-warning", Language.PYTHON, _BASE + "    double(recipient='again')\n", ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "exact-shape-assertion-still-advisory",
        Language.PYTHON,
        _BASE + "    double.assert_called_once_with(recipient='sample')\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "autospec",
        Language.PYTHON,
        _BASE.replace("Mock", "create_autospec").replace("spec=send", "send, spec_set=True"),
    ),
    EvaluationCase("unspecced-owned-by-sarj040", Language.PYTHON, _BASE.replace("spec=send", "")),
    EvaluationCase(
        "unused-callable-only-negative-assertion",
        Language.PYTHON,
        _BASE.replace("double(recipient='sample')", "double.assert_not_called()"),
    ),
    EvaluationCase(
        "external-sdk-signature-is-unresolved",
        Language.PYTHON,
        _BASE.replace("def send(*, recipient: str) -> None:\n    pass", "from external_sdk import send"),
    ),
    EvaluationCase("non-callable-double", Language.PYTHON, _BASE.replace("Mock", "NonCallableMock")),
    EvaluationCase("unrestricted-keywords", Language.PYTHON, _BASE.replace("recipient: str", "**kwargs: object")),
    EvaluationCase("decorated-spec", Language.PYTHON, _BASE.replace("def send", "@decorator\ndef send")),
    EvaluationCase("generic-spec", Language.PYTHON, _BASE.replace("def send", "def send[T]")),
    EvaluationCase(
        "later-spec",
        Language.PYTHON,
        "from unittest.mock import Mock\ndef test_send():\n    double = Mock(spec=send)\n    double(recipient='sample')\ndef send(*, recipient: str):\n    pass\n",
    ),
    EvaluationCase(
        "imported-spec",
        Language.PYTHON,
        _BASE.replace("def send(*, recipient: str) -> None:\n    pass", "from delivery import send"),
    ),
    EvaluationCase(
        "class-spec",
        Language.PYTHON,
        _BASE.replace("def send(*, recipient: str) -> None:\n    pass", "class send:\n    pass"),
    ),
    EvaluationCase("descriptor-spec", Language.PYTHON, _BASE.replace("spec=send", "spec=Delivery.send")),
    EvaluationCase("rebound-spec", Language.PYTHON, _BASE + "send = replacement\n"),
    EvaluationCase("shadowed-spec", Language.PYTHON, _BASE.replace("def test_send():", "def test_send(send):")),
    EvaluationCase("shadowed-constructor", Language.PYTHON, _BASE.replace("def test_send():", "def test_send(Mock):")),
    EvaluationCase(
        "conditional-spec",
        Language.PYTHON,
        _BASE.replace(
            "def send(*, recipient: str) -> None:\n    pass",
            "if condition:\n    def send(*, recipient: str) -> None:\n        pass",
        ),
    ),
    EvaluationCase("rebound-mock", Language.PYTHON, _BASE + "    double = replacement\n"),
    EvaluationCase("deleted-mock", Language.PYTHON, _BASE + "    del double\n"),
    EvaluationCase(
        "global-mock", Language.PYTHON, _BASE.replace("def test_send():", "def test_send():\n    global double")
    ),
    EvaluationCase(
        "mock-read-before-assignment",
        Language.PYTHON,
        _BASE.replace("    double =", "    double(recipient='before')\n    double ="),
    ),
    EvaluationCase("escaped-argument", Language.PYTHON, _BASE + "    consume(double)\n"),
    EvaluationCase("escaped-return", Language.PYTHON, _BASE + "    return double\n"),
    EvaluationCase("escaped-alias", Language.PYTHON, _BASE + "    alias = double\n"),
    EvaluationCase("captured-mock", Language.PYTHON, _BASE + "    def later():\n        double(recipient='later')\n"),
    EvaluationCase("unknown-mock-attribute", Language.PYTHON, _BASE + "    double.custom()\n"),
    EvaluationCase("constructor-wraps", Language.PYTHON, _BASE.replace("spec=send", "spec=send, wraps=send")),
    EvaluationCase(
        "constructor-side-effect", Language.PYTHON, _BASE.replace("spec=send", "spec=send, side_effect=send")
    ),
    EvaluationCase("configured-side-effect", Language.PYTHON, _BASE + "    double.side_effect = send\n"),
    EvaluationCase("configure-mock", Language.PYTHON, _BASE + "    double.configure_mock(side_effect=send)\n"),
    EvaluationCase(
        "dynamic-keywords", Language.PYTHON, _BASE.replace("double(recipient='sample')", "double(**kwargs)")
    ),
    EvaluationCase(
        "mixed-dynamic-keywords",
        Language.PYTHON,
        _BASE.replace("double(recipient='sample')", "double(recipient='sample', **kwargs)"),
    ),
    EvaluationCase(
        "dynamic-positionals",
        Language.PYTHON,
        _BASE.replace("double(recipient='sample')", "double(*args, recipient='sample')"),
    ),
    EvaluationCase(
        "positional-only-use", Language.PYTHON, _BASE.replace("double(recipient='sample')", "double('sample')")
    ),
    EvaluationCase("constructor-unpacking", Language.PYTHON, _BASE.replace("spec=send", "spec=send, **config")),
    EvaluationCase("positional-spec", Language.PYTHON, _BASE.replace("spec=send", "send")),
    EvaluationCase(
        "spec-assignment-alias",
        Language.PYTHON,
        _BASE.replace("def test_send():", "alias = send\ndef test_send():").replace("spec=send", "spec=alias"),
    ),
    EvaluationCase("wildcard-import", Language.PYTHON, "from helpers import *\n" + _BASE),
    EvaluationCase("reflection", Language.PYTHON, _BASE + "    locals()\n"),
    EvaluationCase("generated-banner", Language.PYTHON, "# @generated\n" + _BASE),
    EvaluationCase("strings-only", Language.PYTHON, "example = 'double = Mock(spec=send)'\n"),
    EvaluationCase(
        "captured-constructor",
        Language.PYTHON,
        _BASE.replace("def send", "match replacement:\n    case Mock:\n        pass\ndef send"),
    ),
    EvaluationCase(
        "exception-constructor",
        Language.PYTHON,
        _BASE.replace("def send", "try:\n    pass\nexcept Exception as Mock:\n    pass\ndef send"),
    ),
    EvaluationCase(
        "captured-constructor-alias",
        Language.PYTHON,
        _BASE.replace("import Mock", "import Mock as Double")
        .replace("= Mock(", "= Double(")
        .replace("def send", "match replacement:\n    case Double:\n        pass\ndef send"),
    ),
    EvaluationCase(
        "captured-mock-module",
        Language.PYTHON,
        _BASE.replace(
            "from unittest.mock import Mock",
            "import unittest.mock as doubles\nmatch replacement:\n    case doubles:\n        pass",
        ).replace("= Mock(", "= doubles.Mock("),
    ),
    EvaluationCase(
        "captured-mock-package",
        Language.PYTHON,
        _BASE.replace(
            "from unittest.mock import Mock",
            "import unittest.mock\nmatch replacement:\n    case unittest:\n        pass",
        ).replace("= Mock(", "= unittest.mock.Mock("),
    ),
    EvaluationCase(
        "mapping-rest-spec",
        Language.PYTHON,
        _BASE.replace("def test_send", "match replacement:\n    case {**send}:\n        pass\ndef test_send"),
    ),
    EvaluationCase(
        "mapping-rest-double",
        Language.PYTHON,
        _BASE.replace(
            "    double(recipient=",
            "    match replacement:\n        case {**double}:\n            pass\n    double(recipient=",
        ),
    ),
    EvaluationCase(
        "default-walrus-constructor",
        Language.PYTHON,
        _BASE.replace("def test_send", "def configure(unused=(Mock := replacement)):\n    pass\ndef test_send"),
    ),
    EvaluationCase(
        "qualified-reflection",
        Language.PYTHON,
        "import builtins\n" + _BASE + "    builtins.globals()['Mock'] = replacement\n",
    ),
    EvaluationCase(
        "aliased-reflection",
        Language.PYTHON,
        "from builtins import globals as namespace\n" + _BASE + "    namespace()['Mock'] = replacement\n",
    ),
    EvaluationCase(
        "unrelated-capture",
        Language.PYTHON,
        _BASE.replace("def test_send", "match replacement:\n    case record:\n        pass\ndef test_send"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-default-walrus",
        Language.PYTHON,
        _BASE.replace("def test_send", "def configure(unused=(setting := 1)):\n    pass\ndef test_send"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("malformed", Language.PYTHON, "def broken("),
)


def _check(source: str, path: Path = Path("tests/test_delivery.py")) -> list[Diagnostic]:
    return PreferAutospecForCallableMock().check(path, source)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    findings = _check(case.source)
    assert len(findings) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize(
    "path", ["app/delivery.py", "vendor/tests/test_delivery.py", "generated/tests/test_delivery.py"]
)
def test_scope_exclusions(path: str) -> None:
    assert _check(_BASE, Path(path)) == []


@pytest.mark.parametrize("example", PreferAutospecForCallableMock.public_examples())
def test_public_examples(example: RuleExample) -> None:
    assert len(_check(example.focus_file.source, Path(str(example.focus_path)))) == example.expected_count


def test_metadata_and_anchor() -> None:
    documentation = PreferAutospecForCallableMock.documentation
    assert documentation is not None
    assert documentation.default_level is Severity.WARNING
    assert documentation.autofix is AutofixPolicy.NONE
    finding = _check(_BASE)[0]
    assert (finding.code, finding.line, finding.col) == ("SARJ474", 5, 14)
    assert "create_autospec" in finding.message


def test_autospec_rejects_call_shape_that_plain_function_spec_accepts() -> None:
    def send(*, recipient: str) -> str:
        return recipient

    permissive = Mock(spec=send)
    permissive(wrong_keyword="sample")
    assert permissive.call_count == 1

    with pytest.raises(TypeError):
        create_autospec(send, spec_set=True)(wrong_keyword="sample")


def test_suppression_and_warning_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "test_delivery.py"
    path.write_text(_BASE)
    assert main(["check", "--rule", PreferAutospecForCallableMock.id, str(path)]) == 0
    assert "SARJ474 warning:" in capsys.readouterr().out
    path.write_text(
        _BASE.replace("Mock(spec=send)", "Mock(spec=send)  # sarj-noqa: SARJ474 -- deliberate permissive double")
    )
    assert analyze([PreferAutospecForCallableMock.id], [path]) == []


def test_sarj040_precedence_and_repeatability(tmp_path: Path) -> None:
    path = tmp_path / "test_delivery.py"
    path.write_text(_BASE)
    rules = ["mock-without-spec", PreferAutospecForCallableMock.id]
    first = analyze(rules, [path])
    assert [finding.code for finding in first] == ["SARJ474"]
    assert first == analyze(list(reversed(rules)), [path])
    assert first == analyze(rules, [path])
    path.write_text(_BASE.replace("spec=send", "") + "    double.unknown_attribute()\n")
    assert [finding.code for finding in analyze(rules, [path])] == ["SARJ040"]
