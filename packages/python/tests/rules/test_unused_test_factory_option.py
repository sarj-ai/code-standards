from pathlib import Path, PurePosixPath
from textwrap import indent
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.unused_test_factory_option import UnusedTestFactoryOption


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_FACTORY = "def _make_widget(*, width=3):\n    return Widget(width=width)\n"


def _inside_test(source: str) -> str:
    return "def test_widgets():\n" + indent(source, "    ")


_CASES = (
    EvaluationCase(
        "closed-unused-literal",
        Language.PYTHON,
        _inside_test(_FACTORY + "_make_widget()\n_make_widget()\n"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "closed-invariant-literal",
        Language.PYTHON,
        _inside_test(_FACTORY + "_make_widget()\n_make_widget(width=3)\n"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "closed-invariant-override",
        Language.PYTHON,
        _inside_test(_FACTORY + "_make_widget(width=4)\n_make_widget(width=4)\n"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "closed-positional-option",
        Language.PYTHON,
        _inside_test(
            "def _make_widget(width=3):\n    return Widget(width=width)\n_make_widget(4)\n_make_widget(width=4)\n"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "closed-positional-only-option",
        Language.PYTHON,
        _inside_test(
            "def _make_widget(width=3, /):\n    return Widget(width=width)\n_make_widget(4)\n_make_widget(4)\n"
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "closed-build-helper",
        Language.PYTHON,
        _inside_test((_FACTORY + "_make_widget()\n_make_widget()\n").replace("_make_", "_build_")),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("module-shared-helper", Language.PYTHON, _FACTORY + "_make_widget()\n_make_widget()\n"),
    EvaluationCase(
        "fixture-shared-helper",
        Language.PYTHON,
        _FACTORY + "_make_widget()\n_make_widget()\n",
        path=PurePosixPath("tests/conftest.py"),
    ),
    EvaluationCase(
        "non-test-function-owner",
        Language.PYTHON,
        _inside_test(_FACTORY + "_make_widget()\n_make_widget()\n").replace("test_widgets", "widget_factory"),
    ),
    EvaluationCase("one-call", Language.PYTHON, _inside_test(_FACTORY + "_make_widget()\n")),
    EvaluationCase(
        "varied-literal", Language.PYTHON, _inside_test(_FACTORY + "_make_widget()\n_make_widget(width=4)\n")
    ),
    EvaluationCase(
        "varied-overrides", Language.PYTHON, _inside_test(_FACTORY + "_make_widget(width=4)\n_make_widget(width=5)\n")
    ),
    EvaluationCase(
        "different-literal-types",
        Language.PYTHON,
        _inside_test(_FACTORY + "_make_widget(width=1)\n_make_widget(width=True)\n"),
    ),
    EvaluationCase(
        "dynamic-arguments",
        Language.PYTHON,
        _inside_test(_FACTORY + "_make_widget(width=size)\n_make_widget(width=size)\n"),
    ),
    EvaluationCase(
        "callable-injection-default",
        Language.PYTHON,
        "def _read():\n    return 'value'\n"
        + _inside_test(
            "def _make_widget(*, read=_read):\n    return Widget(read=read)\n_make_widget()\n_make_widget()\n"
        ),
    ),
    EvaluationCase(
        "local-callable-injection-default",
        Language.PYTHON,
        _inside_test(
            "def _read():\n    return 'value'\ndef _make_widget(*, read=_read):\n    return Widget(read=read)\n_make_widget()\n_make_widget()\n"
        ),
    ),
    EvaluationCase(
        "escaped-helper",
        Language.PYTHON,
        _inside_test(_FACTORY + "_make_widget()\n_make_widget()\nregister(_make_widget)\n"),
    ),
    EvaluationCase(
        "returned-helper",
        Language.PYTHON,
        _inside_test(_FACTORY + "_make_widget()\n_make_widget()\nreturn _make_widget\n"),
    ),
    EvaluationCase(
        "aliased-helper", Language.PYTHON, _inside_test(_FACTORY + "alias = _make_widget\nalias()\nalias()\n")
    ),
    EvaluationCase(
        "rebound-helper",
        Language.PYTHON,
        _inside_test(_FACTORY + "_make_widget = other\n_make_widget()\n_make_widget()\n"),
    ),
    EvaluationCase(
        "parameter-shadow",
        Language.PYTHON,
        _inside_test(
            _FACTORY + "def inner(_make_widget):\n    return _make_widget()\n_make_widget()\n_make_widget()\n"
        ),
    ),
    EvaluationCase(
        "required-option",
        Language.PYTHON,
        _inside_test(
            "def _make_widget(*, width):\n    return Widget(width=width)\n_make_widget(width=3)\n_make_widget(width=3)\n"
        ),
    ),
    EvaluationCase(
        "unpacked-arguments",
        Language.PYTHON,
        _inside_test(_FACTORY + "_make_widget(**options)\n_make_widget(**options)\n"),
    ),
    EvaluationCase(
        "unknown-keyword", Language.PYTHON, _inside_test(_FACTORY + "_make_widget(extra=3)\n_make_widget()\n")
    ),
    EvaluationCase(
        "duplicate-keyword",
        Language.PYTHON,
        _inside_test(_FACTORY + "_make_widget(width=3, width=3)\n_make_widget()\n"),
    ),
    EvaluationCase(
        "missing-required",
        Language.PYTHON,
        _inside_test(
            "def _make_widget(required, *, width=3):\n    return Widget(required, width=width)\n_make_widget()\n_make_widget()\n"
        ),
    ),
    EvaluationCase(
        "reflection", Language.PYTHON, _inside_test(_FACTORY + "locals()\n_make_widget()\n_make_widget()\n")
    ),
    EvaluationCase(
        "decorated-helper", Language.PYTHON, _inside_test("@fixture\n" + _FACTORY + "_make_widget()\n_make_widget()\n")
    ),
    EvaluationCase(
        "control-flow-helper",
        Language.PYTHON,
        _inside_test(
            "def _make_widget(*, width=3):\n    if width:\n        return Widget(width=width)\n    return Widget()\n_make_widget()\n_make_widget()\n"
        ),
    ),
    EvaluationCase(
        "exact-suppression",
        Language.PYTHON,
        _inside_test(
            _FACTORY.replace(
                "width=3):", "width=3):  # sarj-noqa: SARJ443 -- optional case knob intentionally retained"
            )
            + "_make_widget()\n_make_widget()\n"
        ),
    ),
    EvaluationCase(
        "generated-header",
        Language.PYTHON,
        "# @generated\n" + _inside_test(_FACTORY + "_make_widget()\n_make_widget()\n"),
    ),
    EvaluationCase("malformed", Language.PYTHON, "def test_widgets(:\n"),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_closed_factory_option_cases(case: EvaluationCase) -> None:
    path = Path("tests/test_widgets.py") if case.path == PurePosixPath("case.txt") else Path(case.path)
    diagnostics = UnusedTestFactoryOption().check(path, case.source)

    assert bool(diagnostics) is (case.expected is ExpectedOutcome.MATCH)
    assert len(diagnostics) <= 1
    assert all(item.severity is Severity.WARNING for item in diagnostics)


@pytest.mark.parametrize(
    "example",
    UnusedTestFactoryOption.public_examples(),
    ids=tuple(example.example_id for example in UnusedTestFactoryOption.public_examples()),
)
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(UnusedTestFactoryOption().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize("path", ["tests/generated/test_widgets.py", "vendor/tests/test_widgets.py", "app/widget.py"])
def test_path_exclusions(path: str) -> None:
    assert UnusedTestFactoryOption().check(Path(path), _CASES[0].source) == []


def test_each_invariant_option_is_reported_once() -> None:
    source = _inside_test(
        "def _make_widget(width=3, *, height=4):\n    return Widget(width=width, height=height)\n_make_widget(5)\n_make_widget(width=6)\n"
    )
    diagnostics = UnusedTestFactoryOption().check(Path("tests/test_widgets.py"), source)

    assert len(diagnostics) == 1
    assert "height" in diagnostics[0].message


def test_native_warning_and_rule_order_are_stable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "test_widgets.py"
    path.write_text(_CASES[0].source)
    assert main(["check", "--rule", UnusedTestFactoryOption.id, str(path)]) == 0
    assert "SARJ443 warning:" in capsys.readouterr().out
    rules = [UnusedTestFactoryOption.id, "mock-without-spec", "no-provably-dead-mock-configuration"]
    assert analyze(rules, [path]) == analyze(list(reversed(rules)), [path])
    assert len(analyze(rules, [path])) == 1


def test_metadata_retains_warning_without_autofix() -> None:
    documentation = UnusedTestFactoryOption.documentation
    assert documentation is not None
    assert documentation.default_level is Severity.WARNING
    assert documentation.autofix is AutofixPolicy.NONE
