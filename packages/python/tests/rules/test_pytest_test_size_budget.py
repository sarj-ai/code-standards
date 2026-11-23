from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.pytest_test_size_budget import PytestTestSizeBudget


def _check(source: str, path: str = "tests/test_case.py") -> list[tuple[int, str]]:
    return [
        (finding.line, finding.message.split(";")[0]) for finding in PytestTestSizeBudget().check(Path(path), source)
    ]


def test_documented_examples() -> None:
    verify_native_rule(PytestTestSizeBudget, analyze)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def test_x(flag):\n    if flag:\n        assert run()\n", (2, "`test_x` uses `if`")),
        ("def test_x():\n    for value in (1, 2):\n        assert run(value)\n", (2, "`test_x` uses `for`")),
        (
            "async def test_x(stream):\n    async for chunk in stream:\n        assert chunk\n",
            (2, "`test_x` uses `async for`"),
        ),
        ("def test_x():\n    while pending():\n        assert poll()\n", (2, "`test_x` uses `while`")),
        (
            "def test_x():\n    for value in (1, 2):\n        with pytest.raises(ValueError):\n            run(value)\n",
            (2, "`test_x` uses `for`"),
        ),
        (
            "def test_x(kind):\n    match kind:\n        case _:\n            assert run()\n",
            (2, "`test_x` uses `match`"),
        ),
        (
            "def test_x():\n    try:\n        run()\n    except ValueError:\n        pass\n",
            (2, "`test_x` uses `try/except`"),
        ),
        ("def test_x():\n    with lock():\n        if ready():\n            assert run()\n", (3, "`test_x` uses `if`")),
        (
            "class TestX:\n    def test_x(self, flag):\n        if flag:\n            assert run()\n",
            (3, "`test_x` uses `if`"),
        ),
    ],
)
def test_reports_the_first_branch_or_loop_once(source: str, expected: tuple[int, str]) -> None:
    assert _check(source) == [expected]


@pytest.mark.parametrize(
    "source",
    [
        "def test_x():\n    assert [value for value in run() if value]\n",
        "def test_x(flag):\n    assert run(1 if flag else 2)\n",
        "def test_x(store):\n    for index in range(3):\n        store.add(index)\n    assert len(store) == 3\n",
        "def test_x():\n    try:\n        assert run()\n    finally:\n        cleanup()\n",
        "def test_x():\n    def fake(value):\n        if value:\n            return 1\n        return 2\n    assert run(fake)\n",
        "def helper(flag):\n    if flag:\n        return run()\n",
        "class Helper:\n    def test_x(self, flag):\n        if flag:\n            assert run()\n",
    ],
)
def test_allows_straight_line_tests_and_non_test_code(source: str) -> None:
    assert _check(source) == []


def test_ignores_non_test_modules_and_conftest() -> None:
    source = "def test_x(flag):\n    if flag:\n        assert run()\n"
    assert _check(source, "src/case.py") == _check(source, "tests/conftest.py") == []


@pytest.mark.parametrize(("count", "expected"), [(15, []), (16, [(1, "`test_x` has 16 statements")])])
def test_statement_budget_excludes_the_docstring(count: int, expected: list[tuple[int, str]]) -> None:
    source = "def test_x():\n    '''Docstring.'''\n" + "    step()\n" * count
    assert _check(source) == expected


def test_counts_nested_statements_but_not_nested_function_bodies() -> None:
    nested = "    def fake():\n" + "        step()\n" * 20 + "    with lock():\n" + "        step()\n" * 14
    assert _check("def test_x():\n" + nested) == [(1, "`test_x` has 16 statements")]
