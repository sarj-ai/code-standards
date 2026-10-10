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
    EvaluationCase(
        "module-shared-helper", Language.PYTHON, _FACTORY + "_make_widget()\n_make_widget()\n", ExpectedOutcome.MATCH
    ),
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


_MODULE_LITERAL = "def _widget(*, width=3):\n    return Widget(width=width)\n_widget()\n_widget(width=3)\n"
_MODULE_CASES = (
    EvaluationCase("private-module-literal", Language.PYTHON, _MODULE_LITERAL, ExpectedOutcome.MATCH),
    EvaluationCase("module-varied-option", Language.PYTHON, _MODULE_LITERAL.replace("width=3)\n", "width=4)\n")),
    EvaluationCase("module-helper-escape", Language.PYTHON, _MODULE_LITERAL + "register(_widget)\n"),
    EvaluationCase(
        "module-helper-patch", Language.PYTHON, _MODULE_LITERAL + "patch('examples.test_widgets._widget')\n"
    ),
    EvaluationCase(
        "module-helper-member-patch",
        Language.PYTHON,
        _MODULE_LITERAL + "patch('examples.test_widgets._widget.__defaults__')\n",
    ),
    EvaluationCase("module-public-contract", Language.PYTHON, _MODULE_LITERAL.replace("_widget", "make_widget")),
    EvaluationCase("module-unpacked-calls", Language.PYTHON, _MODULE_LITERAL + "_widget(**options)\n"),
    EvaluationCase("module-fixture", Language.PYTHON, "@fixture\n" + _MODULE_LITERAL),
    EvaluationCase(
        "module-argument-rebinding",
        Language.PYTHON,
        _MODULE_LITERAL.replace("    return", "    width = other\n    return"),
    ),
)


@pytest.mark.parametrize("case", _MODULE_CASES, ids=tuple(case.case_id for case in _MODULE_CASES))
def test_module_literal_option_cases(case: EvaluationCase) -> None:
    findings = UnusedTestFactoryOption().check(Path("tests/test_widgets.py"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)
    assert len(findings) <= 1


_CALLABLE_FACTORY = "def _read():\n    return 'ready'\ndef _make_widget(*, read=_read):\n    return Widget(read=read)\n"
_CALLABLE_BASE = _CALLABLE_FACTORY + "_make_widget()\n_make_widget()\n"
_CALLABLE_CASES = (
    EvaluationCase("unused-module-local-callable", Language.PYTHON, _CALLABLE_BASE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "unused-async-provider",
        Language.PYTHON,
        _CALLABLE_BASE.replace("def _read", "async def _read"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unused-positional-callable",
        Language.PYTHON,
        _CALLABLE_BASE.replace("(*, read=", "(read="),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unused-positional-only-callable",
        Language.PYTHON,
        _CALLABLE_BASE.replace("(*, read=_read)", "(read=_read, /)"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "thirty-eight-known-omissions",
        Language.PYTHON,
        _CALLABLE_FACTORY + "def test_widgets():\n" + "    _make_widget()\n" * 38,
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "read-only-global-provider",
        Language.PYTHON,
        _CALLABLE_BASE + "def observe():\n    global _read\n    return _read()\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unrelated-default-binding",
        Language.PYTHON,
        _CALLABLE_BASE + "def configure(unused=(setting := 1)):\n    pass\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("one-call", Language.PYTHON, _CALLABLE_FACTORY + "_make_widget()\n"),
    EvaluationCase("no-callers", Language.PYTHON, _CALLABLE_FACTORY),
    EvaluationCase("explicit-default-is-intentional", Language.PYTHON, _CALLABLE_BASE + "_make_widget(read=_read)\n"),
    EvaluationCase("exercised-callback", Language.PYTHON, _CALLABLE_BASE + "_make_widget(read=other)\n"),
    EvaluationCase(
        "positional-callback", Language.PYTHON, _CALLABLE_BASE.replace("(*, read=", "(read=") + "_make_widget(other)\n"
    ),
    EvaluationCase("escaped-factory", Language.PYTHON, _CALLABLE_BASE + "register(_make_widget)\n"),
    EvaluationCase("escaped-provider", Language.PYTHON, _CALLABLE_BASE + "register(_read)\n"),
    EvaluationCase("rebound-factory", Language.PYTHON, _CALLABLE_BASE + "_make_widget = other\n"),
    EvaluationCase(
        "factory-global-writer",
        Language.PYTHON,
        _CALLABLE_BASE + "def configure():\n    global _make_widget\n    _make_widget = other\n",
    ),
    EvaluationCase(
        "factory-default-binding",
        Language.PYTHON,
        _CALLABLE_BASE + "def configure(unused=(_make_widget := other)):\n    pass\n",
    ),
    EvaluationCase(
        "factory-default-mutation", Language.PYTHON, _CALLABLE_BASE + "_make_widget.__kwdefaults__['read'] = other\n"
    ),
    EvaluationCase("rebound-provider", Language.PYTHON, _CALLABLE_BASE + "_read = other\n"),
    EvaluationCase("deleted-provider", Language.PYTHON, _CALLABLE_BASE + "del _read\n"),
    EvaluationCase(
        "provider-global-writer",
        Language.PYTHON,
        _CALLABLE_BASE + "def configure():\n    global _read\n    _read = other\n",
    ),
    EvaluationCase(
        "provider-default-binding",
        Language.PYTHON,
        _CALLABLE_BASE + "def configure(unused=(_read := other)):\n    pass\n",
    ),
    EvaluationCase(
        "provider-attribute-mutation", Language.PYTHON, _CALLABLE_BASE + "_read.__code__ = other.__code__\n"
    ),
    EvaluationCase(
        "provider-subscript-mutation", Language.PYTHON, _CALLABLE_BASE + "_read.__kwdefaults__['option'] = other\n"
    ),
    EvaluationCase("provider-patch-string", Language.PYTHON, _CALLABLE_BASE + "patch('sample.tests._read', other)\n"),
    EvaluationCase(
        "provider-member-patch-string",
        Language.PYTHON,
        _CALLABLE_BASE + "patch('sample.tests._read.__code__', other)\n",
    ),
    EvaluationCase(
        "factory-patch-string",
        Language.PYTHON,
        _CALLABLE_BASE + "patch('sample.tests._make_widget.__kwdefaults__', other)\n",
    ),
    EvaluationCase(
        "provider-patch-attribute", Language.PYTHON, _CALLABLE_BASE + "monkeypatch.setattr(module, '_read', other)\n"
    ),
    EvaluationCase("duplicate-provider", Language.PYTHON, _CALLABLE_BASE + "def _read():\n    return 'changed'\n"),
    EvaluationCase(
        "imported-provider",
        Language.PYTHON,
        _CALLABLE_BASE.replace("def _read():\n    return 'ready'\n", "from dependency import _read\n"),
    ),
    EvaluationCase(
        "late-provider",
        Language.PYTHON,
        "def _make_widget(*, read=_read):\n    return Widget(read=read)\ndef _read():\n    return 'ready'\n_make_widget()\n_make_widget()\n",
    ),
    EvaluationCase("decorated-provider", Language.PYTHON, "@decorate\n" + _CALLABLE_BASE),
    EvaluationCase(
        "decorated-factory", Language.PYTHON, _CALLABLE_BASE.replace("def _make_widget", "@decorate\ndef _make_widget")
    ),
    EvaluationCase(
        "provider-shadowed-by-argument", Language.PYTHON, _CALLABLE_BASE + "def another(_read):\n    return _read\n"
    ),
    EvaluationCase(
        "provider-pattern-capture", Language.PYTHON, _CALLABLE_BASE + "match value:\n    case _read:\n        pass\n"
    ),
    EvaluationCase(
        "provider-exception-capture",
        Language.PYTHON,
        _CALLABLE_BASE + "try:\n    act()\nexcept Exception as _read:\n    pass\n",
    ),
    EvaluationCase(
        "factory-argument-rebound",
        Language.PYTHON,
        _CALLABLE_BASE.replace("    return Widget", "    read = other\n    return Widget"),
    ),
    EvaluationCase("unpacked-caller", Language.PYTHON, _CALLABLE_BASE + "_make_widget(**options)\n"),
    EvaluationCase("wildcard-import", Language.PYTHON, "from dependency import *\n" + _CALLABLE_BASE),
    EvaluationCase("reflection", Language.PYTHON, _CALLABLE_BASE + "globals()['_read'] = other\n"),
    EvaluationCase("exported-factory", Language.PYTHON, _CALLABLE_BASE + "__all__ = ['_make_widget']\n"),
    EvaluationCase("conftest-shared-factory", Language.PYTHON, _CALLABLE_BASE, path=PurePosixPath("tests/conftest.py")),
    EvaluationCase("shared-export-alias", Language.PYTHON, _CALLABLE_BASE + "make_widget = _make_widget\n"),
    EvaluationCase(
        "suppressed-callable",
        Language.PYTHON,
        _CALLABLE_BASE.replace("read=_read):", "read=_read):  # sarj-noqa: SARJ443 -- preserve extension contract"),
    ),
    EvaluationCase(
        "other-suppression-keeps-signal",
        Language.PYTHON,
        _CALLABLE_BASE.replace("read=_read):", "read=_read):  # sarj-noqa: SARJ040 -- separate policy"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("generated-callable", Language.PYTHON, "# @generated\n" + _CALLABLE_BASE),
    EvaluationCase("malformed-callable", Language.PYTHON, "def _make_widget(:\n"),
)


@pytest.mark.parametrize("case", _CALLABLE_CASES, ids=tuple(case.case_id for case in _CALLABLE_CASES))
def test_module_callable_default_cases(case: EvaluationCase) -> None:
    path = Path("tests/test_widgets.py") if case.path == PurePosixPath("case.txt") else Path(case.path)
    diagnostics = UnusedTestFactoryOption().check(path, case.source)

    assert bool(diagnostics) is (case.expected is ExpectedOutcome.MATCH)
    assert len(diagnostics) <= 1
    assert all(item.severity is Severity.WARNING for item in diagnostics)


def test_callable_remediation_keeps_remaining_literal_diagnostic() -> None:
    source = (
        "def _read():\n    return 'ready'\n"
        "def _make_widget(*, width=3, read=_read):\n    return Widget(width=width, read=read)\n"
        "_make_widget()\n_make_widget()\n"
    )
    diagnostics = UnusedTestFactoryOption().check(Path("tests/test_widgets.py"), source)

    assert [".width`" in item.message for item in diagnostics] == [True, False]
    assert "known direct caller" in diagnostics[1].message
    remaining = UnusedTestFactoryOption().check(
        Path("tests/test_widgets.py"),
        source.replace("*, width=3, read=_read", "*, width=3").replace("read=read", "read=_read"),
    )
    assert remaining == diagnostics[:1]
