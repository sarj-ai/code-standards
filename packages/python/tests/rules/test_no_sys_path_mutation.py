from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.no_sys_path_mutation import NoSysPathMutation


def _lines(source: str) -> list[int]:
    return [finding.line for finding in NoSysPathMutation().check(Path("service/bootstrap.py"), source)]


def test_documented_examples() -> None:
    verify_native_rule(NoSysPathMutation, analyze)


@pytest.mark.parametrize(
    "method",
    [
        "append",
        "extend",
        "insert",
        "remove",
        "pop",
        "clear",
        "reverse",
        "sort",
        "__setitem__",
        "__delitem__",
        "__iadd__",
        "__imul__",
        "__init__",
    ],
)
def test_rejects_path_mutators(method: str) -> None:
    assert _lines(f"import sys\nsys.path.{method}(value)\n") == [2]


@pytest.mark.parametrize(
    "mutation",
    [
        "sys.path = values",
        "sys.path: list[str] = values",
        "sys.path += values",
        "sys.path *= 2",
        "sys.path[0] = value",
        "sys.path[:] = values",
        "sys.path[0] += value",
        "del sys.path[0]",
        "del sys.path[:]",
        "del sys.path",
        "setattr(sys, 'path', values)",
        "delattr(sys, 'path')",
        "list.append(sys.path, value)",
        "list.__setitem__(sys.path, 0, value)",
        "list.__init__(sys.path, values)",
    ],
)
def test_rejects_path_writes_without_duplicate_target_reports(mutation: str) -> None:
    assert _lines(f"import sys\n{mutation}\n") == [2]


@pytest.mark.parametrize("operation", ["setitem", "delitem", "iadd", "imul", "iconcat"])
def test_rejects_operator_mutators(operation: str) -> None:
    assert _lines(f"import operator as operations\nimport sys\noperations.{operation}(sys.path, value)\n") == [3]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import sys as runtime\nruntime.path.append(value)\n", [2]),
        ("from sys import path as search\nsearch.append(value)\n", [2]),
        ("from sys import path as search\nsearch += values\n", [2]),
        ("import sys\nsearch = sys.path\nsearch[0] = value\n", [3]),
        ("import sys\nsearch = sys.path\nsearch *= 2\n", [3]),
        ("import sys\nruntime = sys\nruntime.path.append(value)\n", [3]),
        ("import sys\nappend = sys.path.append\nappend(value)\n", [3]),
        ("def bootstrap():\n    import sys as runtime\n    runtime.path.insert(0, value)\n", [3]),
        (
            "import sys\ndef outer():\n    search = sys.path\n    def inner():\n        search.append(value)\n    return inner\n",
            [5],
        ),
        ("import sys\nclass State:\n    sys = custom\n    def bootstrap(self):\n        sys.path.append(value)\n", [5]),
    ],
)
def test_resolves_import_and_value_aliases(source: str, expected: list[int]) -> None:
    assert _lines(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "import sys\npaths = tuple(sys.path)\n",
        "import sys\npaths = list(sys.path)\npaths.append(value)\n",
        "import sys\npaths = sys.path.copy()\npaths.append(value)\n",
        "import sys\npaths = sys.path[:]\npaths.append(value)\n",
        "import sys\nsys.path[:].append(value)\n",
        "import sys\nposition = sys.path.index(value)\n",
        "import sys\ncount = sys.path.count(value)\n",
        "import sys\npaths = sys.path\npaths = []\npaths.append(value)\n",
        "import sys\npaths = sys.path\npaths = []\n",
        "import sys\npaths = sys.path\ndel paths\n",
        "import sys\ndef bootstrap(sys):\n    sys.path.append(value)\n",
        "import application as sys\nsys.path.append(value)\n",
        "class State:\n    def bootstrap(self, sys):\n        sys.path.append(value)\n",
        "text = 'sys.path.append(value)'\n# sys.path = values\n",
        "import sys\nsys.path.append(\n",
    ],
)
def test_accepts_reads_copies_shadowed_names_and_malformed_source(source: str) -> None:
    assert _lines(source) == []
