from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import analyze, main
from sarj_python_lint.rule_base import AutofixPolicy, Severity
from sarj_python_lint.rules.unused_test_factory_option import UnusedTestFactoryOption


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_FACTORY = "def _make_widget(*, width=3):\n    return Widget(width=width)\n"
_CASES = (
    pytest.param(
        _FACTORY + "def test_widget():\n    assert _make_widget()\n", True, "tests/test_widget.py", id="unused-literal"
    ),
    pytest.param(
        _FACTORY + "def test_widget():\n    assert _make_widget(width=4)\n",
        False,
        "tests/test_widget.py",
        id="supplied",
    ),
    pytest.param(
        _FACTORY + "_make_widget()\n_make_widget(width=3)\n", True, "tests/test_widget.py", id="mixed-same-default"
    ),
    pytest.param(
        _FACTORY + "_make_widget(width=4)\n_make_widget(width=4)\n", True, "tests/test_widget.py", id="same-override"
    ),
    pytest.param(
        _FACTORY + "_make_widget()\n_make_widget(width=4)\n",
        False,
        "tests/test_widget.py",
        id="mixed-different-default",
    ),
    pytest.param(
        _FACTORY + "_make_widget(width=4)\n_make_widget(width=5)\n",
        False,
        "tests/test_widget.py",
        id="different-overrides",
    ),
    pytest.param(
        _FACTORY + "_make_widget(width=1)\n_make_widget(width=True)\n",
        False,
        "tests/test_widget.py",
        id="typed-literals",
    ),
    pytest.param(
        _FACTORY + "_make_widget(width=value)\n_make_widget(width=value)\n",
        False,
        "tests/test_widget.py",
        id="dynamic-arguments",
    ),
    pytest.param(
        _FACTORY + "_make_widget(width=[])\n_make_widget(width=[])\n",
        False,
        "tests/test_widget.py",
        id="mutable-arguments",
    ),
    pytest.param(
        "def _make_widget(width=3):\n    return Widget(width=width)\n_make_widget(4)\n_make_widget(width=4)\n",
        True,
        "tests/test_widget.py",
        id="positional-and-keyword",
    ),
    pytest.param(
        "def _make_widget(width=3, /):\n    return Widget(width=width)\n_make_widget(4)\n_make_widget(4)\n",
        True,
        "tests/test_widget.py",
        id="positional-only",
    ),
    pytest.param(
        "def _make_widget(required, *, width=3):\n    return Widget(required, width=width)\n_make_widget(width=3)\n_make_widget(width=3)\n",
        False,
        "tests/test_widget.py",
        id="missing-required",
    ),
    pytest.param(
        "def _make_widget(width=3):\n    return Widget(width=width)\n_make_widget(4, width=4)\n_make_widget(4)\n",
        False,
        "tests/test_widget.py",
        id="double-binding",
    ),
    pytest.param(
        "def _make_widget(width):\n    return Widget(width=width)\n_make_widget(4)\n_make_widget(4)\n",
        False,
        "tests/test_widget.py",
        id="required-option",
    ),
    pytest.param(
        _FACTORY + "_make_widget(width=3, width=3)\n_make_widget(width=3)\n",
        False,
        "tests/test_widget.py",
        id="duplicate-keyword",
    ),
    pytest.param(
        _FACTORY + "_make_widget(width=3, extra=0)\n_make_widget(width=3)\n",
        False,
        "tests/test_widget.py",
        id="unknown-keyword",
    ),
    pytest.param(
        _FACTORY + "_make_widget(3)\n_make_widget(3)\n", False, "tests/test_widget.py", id="too-many-positional"
    ),
    pytest.param(
        "def _make_widget(*, required, width=3):\n    return Widget(required, width=width)\n_make_widget(width=3)\n_make_widget(width=3)\n",
        False,
        "tests/test_widget.py",
        id="required-keyword",
    ),
    pytest.param(
        "def _make_widget(width=3, /):\n    return Widget(width=width)\n_make_widget(width=3)\n_make_widget(width=3)\n",
        False,
        "tests/test_widget.py",
        id="posonly-keyword",
    ),
    pytest.param(
        "def _make_widget(*, width=3):  # sarj-noqa: SARJ443 -- shared externally\n    return Widget(width=width)\n_make_widget(width=4)\n_make_widget(width=4)\n",
        False,
        "tests/test_widget.py",
        id="invariant-suppressed",
    ),
    pytest.param(_FACTORY, False, "tests/test_widget.py", id="no-callers"),
    pytest.param(
        _FACTORY + "import builtins\nbuiltins.globals()\n_make_widget()\n",
        False,
        "tests/test_widget.py",
        id="qualified-reflection",
    ),
    pytest.param(
        _FACTORY + "from builtins import globals as namespace\nnamespace()\n_make_widget()\n",
        False,
        "tests/test_widget.py",
        id="aliased-reflection",
    ),
    pytest.param(
        _FACTORY + "from elsewhere import *\n_make_widget()\n", False, "tests/test_widget.py", id="star-import"
    ),
    pytest.param(
        _FACTORY + "monkeypatch.setattr(module, '_make_widget', replacement)\n_make_widget()\n",
        False,
        "tests/test_widget.py",
        id="string-replacement",
    ),
    pytest.param(
        _FACTORY + "match value:\n    case _make_widget:\n        _make_widget()\n",
        False,
        "tests/test_widget.py",
        id="match-binding",
    ),
    pytest.param(
        _FACTORY + "try:\n    pass\nexcept Exception as _make_widget:\n    _make_widget()\n",
        False,
        "tests/test_widget.py",
        id="exception-binding",
    ),
    pytest.param(_FACTORY + "factory = _make_widget\n", False, "tests/test_widget.py", id="escaped"),
    pytest.param(_FACTORY + "register(_make_widget)\n", False, "tests/test_widget.py", id="callback"),
    pytest.param(_FACTORY + "_make_widget(**options)\n", False, "tests/test_widget.py", id="kwargs"),
    pytest.param(_FACTORY + "_make_widget(*options)\n", False, "tests/test_widget.py", id="starargs"),
    pytest.param("@pytest.fixture\n" + _FACTORY + "_make_widget()\n", False, "tests/test_widget.py", id="decorated"),
    pytest.param(
        _FACTORY.replace("_make_widget", "make_widget") + "make_widget()\n", False, "tests/test_widget.py", id="public"
    ),
    pytest.param(_FACTORY + "_make_widget = other\n_make_widget()\n", False, "tests/test_widget.py", id="rebound"),
    pytest.param(
        _FACTORY + "def test_widget(_make_widget):\n    _make_widget()\n",
        False,
        "tests/test_widget.py",
        id="parameter-shadow",
    ),
    pytest.param(
        _FACTORY + "def _make_widget():\n    pass\n_make_widget()\n",
        False,
        "tests/test_widget.py",
        id="definition-shadow",
    ),
    pytest.param(
        _FACTORY + "from elsewhere import _make_widget\n_make_widget()\n",
        False,
        "tests/test_widget.py",
        id="import-shadow",
    ),
    pytest.param(_FACTORY + "globals()['_make_widget']()\n", False, "tests/test_widget.py", id="reflection"),
    pytest.param(
        _FACTORY + "__all__ = ['_make_widget']\n_make_widget()\n", False, "tests/test_widget.py", id="exported"
    ),
    pytest.param(
        _FACTORY.replace("width=3", "width=[]") + "_make_widget()\n",
        False,
        "tests/test_widget.py",
        id="mutable-default",
    ),
    pytest.param(
        _FACTORY.replace("width=3", "width=DEFAULT_WIDTH") + "_make_widget()\n",
        False,
        "tests/test_widget.py",
        id="captured-default",
    ),
    pytest.param(
        _FACTORY.replace("width=3", "width=next_width()") + "_make_widget()\n",
        False,
        "tests/test_widget.py",
        id="effectful-default",
    ),
    pytest.param(
        "def _check_widget(width=3):\n    return width > 0\n_check_widget()\n",
        False,
        "tests/test_widget.py",
        id="non-factory",
    ),
    pytest.param(
        "def test_widget():\n    def _make_widget(width=3):\n        return Widget(width=width)\n    assert _make_widget()\n",
        False,
        "tests/test_widget.py",
        id="nested",
    ),
    pytest.param("async " + _FACTORY + "_make_widget()\n", False, "tests/test_widget.py", id="async"),
    pytest.param(
        _FACTORY + "inspect.signature(_make_widget)\n_make_widget()\n",
        False,
        "tests/test_widget.py",
        id="signature-inspection",
    ),
    pytest.param(
        _FACTORY.replace(":\n", ":  # sarj-noqa: SARJ443 -- shared outside this file\n", 1) + "_make_widget()\n",
        False,
        "tests/test_widget.py",
        id="suppressed",
    ),
    pytest.param("def _make_widget(:\n", False, "tests/test_widget.py", id="malformed"),
    pytest.param(_FACTORY + "_make_widget()\n", False, "app/widgets.py", id="production"),
)


@pytest.mark.parametrize(("source", "expected", "path"), _CASES)
def test_factory_option_boundaries(source: str, expected: bool, path: str) -> None:
    diagnostics = UnusedTestFactoryOption().check(Path(path), source)
    assert bool(diagnostics) is expected
    assert all(item.severity is Severity.WARNING for item in diagnostics)


def test_reports_only_unsupplied_options_once() -> None:
    source = (
        "def _make_widget(width=3, *, height=4):\n    return Widget(width=width, height=height)\n"
        "_make_widget(5)\n_make_widget(width=6)\n"
    )
    diagnostics = UnusedTestFactoryOption().check(Path("tests/test_widget.py"), source)
    assert len(diagnostics) == 1
    assert "height" in diagnostics[0].message


@pytest.mark.parametrize(
    "example",
    UnusedTestFactoryOption.public_examples(),
    ids=tuple(example.example_id for example in UnusedTestFactoryOption.public_examples()),
)
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(UnusedTestFactoryOption().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    "body",
    [
        "    item = Widget(width=width)\n    return item\n",
        "    chosen = width\n    return Widget(width=chosen)\n",
        '    """Build an isolated widget."""\n    item: Widget = Widget(width=width)\n    return item\n',
    ],
)
def test_straight_line_factory_options(body: str) -> None:
    source = f"def _make_widget(*, width=3):\n{body}_make_widget()\n_make_widget(width=3)\n"
    assert len(UnusedTestFactoryOption().check(Path("tests/test_widget.py"), source)) == 1
    assert (
        UnusedTestFactoryOption().check(Path("tests/test_widget.py"), source.replace("width=3)", "width=4)", 1)) == []
    )


@pytest.mark.parametrize(
    "body",
    [
        "    if width:\n        return Widget(width=width)\n    return Widget()\n",
        "    item = Widget(width=width)\n    item.save()\n    return item\n",
        "    target.width = width\n    return target\n",
        "    return width\n",
    ],
)
def test_complex_helpers_remain_excluded(body: str) -> None:
    source = f"def _make_widget(*, width=3):\n{body}_make_widget()\n"
    assert UnusedTestFactoryOption().check(Path("tests/test_widget.py"), source) == []


_CALLABLE_FACTORY = "def _read():\n    return 'value'\ndef _make_widget(*, read=_read):\n    return Widget(read=read)\n"
_CALLABLE_BASE = _CALLABLE_FACTORY + "_make_widget()\n"
_CALLABLE_CASES = (
    EvaluationCase("unused-local-function", Language.PYTHON, _CALLABLE_BASE, ExpectedOutcome.MATCH),
    EvaluationCase(
        "unused-local-async-function",
        Language.PYTHON,
        _CALLABLE_BASE.replace("def _read", "async def _read"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unused-build-helper", Language.PYTHON, _CALLABLE_BASE.replace("_make_", "_build_"), ExpectedOutcome.MATCH
    ),
    EvaluationCase(
        "unused-positional-option",
        Language.PYTHON,
        _CALLABLE_BASE.replace("(*, read=_read)", "(read=_read)"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "unused-positional-only-option",
        Language.PYTHON,
        _CALLABLE_BASE.replace("(*, read=_read)", "(read=_read, /)"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "many-omitting-callers", Language.PYTHON, _CALLABLE_BASE + "_make_widget()\n", ExpectedOutcome.MATCH
    ),
    EvaluationCase("exercised-callback", Language.PYTHON, _CALLABLE_FACTORY + "_make_widget(read=other)\n"),
    EvaluationCase("explicit-default", Language.PYTHON, _CALLABLE_FACTORY + "_make_widget(read=_read)\n"),
    EvaluationCase("mixed-callback-callers", Language.PYTHON, _CALLABLE_BASE + "_make_widget(read=other)\n"),
    EvaluationCase(
        "positional-callback",
        Language.PYTHON,
        _CALLABLE_BASE.replace("(*, ", "(").replace("_make_widget()", "_make_widget(other)"),
    ),
    EvaluationCase("no-callers", Language.PYTHON, _CALLABLE_FACTORY),
    EvaluationCase("unpacked-caller", Language.PYTHON, _CALLABLE_FACTORY + "_make_widget(**options)\n"),
    EvaluationCase("escaped-factory", Language.PYTHON, _CALLABLE_BASE + "register(_make_widget)\n"),
    EvaluationCase(
        "factory-default-mutation", Language.PYTHON, _CALLABLE_BASE + "_make_widget.__kwdefaults__['read'] = other\n"
    ),
    EvaluationCase("rebound-provider", Language.PYTHON, _CALLABLE_BASE + "_read = other\n"),
    EvaluationCase("deleted-provider", Language.PYTHON, _CALLABLE_BASE + "del _read\n"),
    EvaluationCase("provider-attribute-write", Language.PYTHON, _CALLABLE_BASE + "_read.__code__ = other.__code__\n"),
    EvaluationCase("qualified-provider-write", Language.PYTHON, _CALLABLE_BASE + "module._read = other\n"),
    EvaluationCase(
        "patched-provider", Language.PYTHON, _CALLABLE_BASE + "monkeypatch.setattr(module, '_read', other)\n"
    ),
    EvaluationCase(
        "qualified-patch-target",
        Language.PYTHON,
        _CALLABLE_BASE + "monkeypatch.setattr('example.tests._read', other)\n",
    ),
    EvaluationCase(
        "qualified-factory-patch-target",
        Language.PYTHON,
        _CALLABLE_BASE + "patch('example.tests._make_widget.__kwdefaults__', other)\n",
    ),
    EvaluationCase("duplicate-provider", Language.PYTHON, _CALLABLE_BASE + "def _read():\n    return 'other'\n"),
    EvaluationCase(
        "imported-provider",
        Language.PYTHON,
        _CALLABLE_BASE.replace("def _read():\n    return 'value'\n", "from dependency import _read\n"),
    ),
    EvaluationCase("shadowing-import", Language.PYTHON, _CALLABLE_BASE + "from dependency import _read\n"),
    EvaluationCase("decorated-provider", Language.PYTHON, "@decorate\n" + _CALLABLE_BASE),
    EvaluationCase(
        "conditional-provider",
        Language.PYTHON,
        _CALLABLE_BASE.replace(
            "def _read():\n    return 'value'", "if enabled:\n    def _read():\n        return 'value'"
        ),
    ),
    EvaluationCase(
        "late-provider",
        Language.PYTHON,
        "def _make_widget(*, read=_read):\n    return Widget(read=read)\ndef _read():\n    return 'value'\n_make_widget()\n",
    ),
    EvaluationCase(
        "provider-parameter-shadow", Language.PYTHON, _CALLABLE_BASE + "def test_other(_read):\n    return _read()\n"
    ),
    EvaluationCase("provider-local-shadow", Language.PYTHON, _CALLABLE_BASE + "def test_other():\n    _read = other\n"),
    EvaluationCase(
        "factory-local-shadow",
        Language.PYTHON,
        _CALLABLE_BASE.replace("    return Widget", "    _read = other\n    return Widget"),
    ),
    EvaluationCase(
        "provider-pattern-binding", Language.PYTHON, _CALLABLE_BASE + "match value:\n    case _read:\n        pass\n"
    ),
    EvaluationCase(
        "provider-exception-binding",
        Language.PYTHON,
        _CALLABLE_BASE + "try:\n    pass\nexcept Exception as _read:\n    pass\n",
    ),
    EvaluationCase("provider-walrus-binding", Language.PYTHON, _CALLABLE_BASE + "if (_read := other):\n    pass\n"),
    EvaluationCase("provider-loop-binding", Language.PYTHON, _CALLABLE_BASE + "for _read in callbacks:\n    pass\n"),
    EvaluationCase(
        "provider-alias",
        Language.PYTHON,
        _CALLABLE_BASE.replace("def _make_widget", "chosen = _read\ndef _make_widget").replace(
            "read=_read)", "read=chosen)"
        ),
    ),
    EvaluationCase("effectful-default", Language.PYTHON, _CALLABLE_BASE.replace("read=_read)", "read=_read())")),
    EvaluationCase("wildcard-import", Language.PYTHON, "from dependency import *\n" + _CALLABLE_BASE),
    EvaluationCase("reflection", Language.PYTHON, _CALLABLE_BASE + "globals()['_read'] = other\n"),
    EvaluationCase("generated-source", Language.PYTHON, "# @generated\n" + _CALLABLE_BASE),
    EvaluationCase("malformed-source", Language.PYTHON, "def _make_widget(:\n"),
    EvaluationCase(
        "suppressed-option",
        Language.PYTHON,
        _CALLABLE_BASE.replace("read=_read):", "read=_read):  # sarj-noqa: SARJ443 -- shared test helper"),
    ),
)


@pytest.mark.parametrize("case", _CALLABLE_CASES, ids=tuple(case.case_id for case in _CALLABLE_CASES))
def test_callable_default_labeled_cases(case: EvaluationCase) -> None:
    diagnostics = UnusedTestFactoryOption().check(Path("tests/test_widget.py"), case.source)
    assert len(diagnostics) == (1 if case.expected is ExpectedOutcome.MATCH else 0)
    assert all(item.severity is Severity.WARNING for item in diagnostics)


def test_keeps_exercised_callback_beside_unused_callback() -> None:
    source = (
        "def _read():\n    return 'value'\n"
        "def _make_widget(*, first=_read, second=_read):\n    return Widget(first=first, second=second)\n"
        "_make_widget(first=other)\n_make_widget()\n"
    )
    diagnostics = UnusedTestFactoryOption().check(Path("tests/test_widget.py"), source)
    assert len(diagnostics) == 1
    assert "second" in diagnostics[0].message
    assert "stable local callable" in diagnostics[0].message


@pytest.mark.parametrize("path", ["tests/generated/test_widget.py", "vendor/tests/test_widget.py", "app/widget.py"])
def test_callable_default_path_exclusions(path: str) -> None:
    assert UnusedTestFactoryOption().check(Path(path), _CALLABLE_BASE) == []


def test_callable_default_warning_and_exact_suppression(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "test_widget.py"
    path.write_text(_CALLABLE_BASE)
    assert main(["check", "--rule", UnusedTestFactoryOption.id, str(path)]) == 0
    assert "SARJ443 warning:" in capsys.readouterr().out
    path.write_text(_CALLABLE_BASE.replace("read=_read):", "read=_read):  # sarj-noqa: SARJ443 -- shared test helper"))
    assert analyze([UnusedTestFactoryOption.id], [path]) == []
    path.write_text(_CALLABLE_BASE.replace("read=_read):", "read=_read):  # sarj-noqa: SARJ040 -- separate policy"))
    rules = [UnusedTestFactoryOption.id, "mock-without-spec", "no-provably-dead-mock-configuration"]
    first = analyze(rules, [path])
    assert first == analyze(list(reversed(rules)), [path])
    assert len(first) == 1
    assert first[0].code == "SARJ443"


def test_callable_default_metadata_retains_warning_without_autofix() -> None:
    documentation = UnusedTestFactoryOption.documentation
    assert documentation is not None
    assert documentation.default_level is Severity.WARNING
    assert documentation.autofix is AutofixPolicy.NONE
