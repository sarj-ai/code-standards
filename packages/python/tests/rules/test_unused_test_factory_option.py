from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
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
