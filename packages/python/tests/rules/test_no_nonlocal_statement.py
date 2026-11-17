from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules import DEFAULT_REGISTRY
from sarj_python_lint.rules.no_nonlocal_statement import NoNonlocalStatement


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


def _check(source: str, path: str = "app/counter.py") -> list[Diagnostic]:
    return NoNonlocalStatement().check(Path(path), source)


def test_documented_examples() -> None:
    verify_native_rule(NoNonlocalStatement, analyze)


def test_rule_is_enabled_by_default_as_an_error() -> None:
    rule = DEFAULT_REGISTRY["no-nonlocal-statement"]
    assert rule is NoNonlocalStatement
    assert rule.documentation is not None
    assert rule.documentation.default_level is Severity.ERROR


@pytest.mark.parametrize(
    "statement",
    ["nonlocal value", "nonlocal value, other", "nonlocal value; value += 1", "nonlocal \\\n            value"],
    ids=["one-name", "multiple-names", "semicolon", "continued-line"],
)
def test_reports_the_statement_once(statement: str) -> None:
    source = f"def outer():\n    value = other = 0\n    def update():\n        {statement}\n        return value\n"
    assert [(item.line, item.col, item.code, item.severity) for item in _check(source)] == [
        (4, 9, "SARJ578", Severity.ERROR)
    ]


def test_visits_async_callbacks_and_nested_statements_in_source_order() -> None:
    source = (
        "def outer():\n"
        "    value = 0\n"
        "    async def update():\n"
        "        nonlocal value\n"
        "        if value:\n"
        "            def reset():\n"
        "                nonlocal value\n"
        "                value = 0\n"
        "            reset()\n"
    )
    assert [(item.line, item.col) for item in _check(source)] == [(4, 9), (7, 17)]


@pytest.mark.parametrize(
    ("directive", "expected"),
    [
        ("# sarj-noqa: SARJ578 -- Required closure-binding fixture for the compiler contract.", 0),
        ("# noqa: SARJ578 -- Required closure-binding fixture for the compiler contract.", 1),
        ("# sarj-noqa: SARJ999 -- Unrelated compiler fixture exception.", 1),
        ("# ruff: ignore[global-statement] -- A different engine owns global declarations.", 1),
    ],
    ids=["exact", "legacy-noqa", "different-rule", "different-engine"],
)
def test_suppressions_are_specific_to_this_rule(directive: str, expected: int) -> None:
    source = (
        f"def outer():\n    value = 0\n    def read():\n        nonlocal value  {directive}\n        return value\n"
    )
    assert len(_check(source)) == expected


@pytest.mark.parametrize(
    "source",
    [
        "# nonlocal value\n",
        "source = 'nonlocal value'\n",
        '"""nonlocal value"""\n',
        "nonlocal_value = 1\n",
        "def outer(value):\n    def read():\n        return value\n    return read()\n",
        "value = 0\ndef update():\n    global value\n    value += 1\n",
        "def outer(:\n    nonlocal value\n",
    ],
    ids=["comment", "string", "docstring", "identifier", "closure-read", "ruff-global-owner", "malformed"],
)
def test_does_not_report_other_syntax(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("path", ["generated/counter.py", "vendor/counter.py", "app/counter.py"])
def test_generated_and_vendored_sources_are_excluded(path: str) -> None:
    source = (
        "# This file is generated; do not edit.\n" if path.startswith("app/") else ""
    ) + "def outer():\n    value = 0\n    def update():\n        nonlocal value\n        value += 1\n"
    assert _check(source, path) == []
