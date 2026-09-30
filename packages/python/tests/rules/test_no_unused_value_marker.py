from pathlib import Path
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_unused_value_marker import NoUnusedValueMarker


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/service.py") -> list[Diagnostic]:
    return NoUnusedValueMarker().check(Path(path), textwrap.dedent(source))


@pytest.mark.parametrize(
    "example",
    NoUnusedValueMarker.public_examples(),
    ids=[example.example_id for example in NoUnusedValueMarker.public_examples()],
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


@pytest.mark.parametrize(
    "statement",
    [
        "_ = value",
        "_ = first, second",
        "_ = (first, second)",
        "_ = [first, [second, third]]",
        "_ = execute()",
        "_ = object.attribute",
        "_ = values[index]",
        "_ = 1",
        "_ = value = load()",
        "_: object = load()",
    ],
)
def test_flags_standalone_underscore_assignments(statement: str) -> None:
    diagnostics = _check(statement)

    assert [(item.line, item.col, item.code, item.severity) for item in diagnostics] == [
        (1, 1, "SARJ452", Severity.WARNING)
    ]


@pytest.mark.parametrize(
    "source",
    [
        "value, _ = load_pair()",
        "for _ in values:\n    consume()",
        "_: object",
        "def handler(_value: object) -> None:\n    return",
        "from gettext import gettext as _",
    ],
)
def test_allows_other_underscore_conventions(source: str) -> None:
    assert _check(source) == []


def test_reports_nested_markers_in_source_order() -> None:
    diagnostics = _check(
        """
        def outer(first: object) -> None:
            _ = first
            def inner(second: object) -> None:
                _ = second
                _ = first
        """
    )

    assert [(item.line, item.col) for item in diagnostics] == [(3, 5), (5, 9), (6, 9)]


@pytest.mark.parametrize(
    "source",
    [
        "def callback(cwd: Path) -> None:\n    _ = cwd\n",
        "def callback(cwd: Path, capture_output: bool) -> None:\n    _ = cwd, capture_output\n",
        "def callback(cwd: Path, capture_output: bool) -> None:\n    _ = (cwd, capture_output)\n",
        "async def say(message: str, **kwargs: object) -> None:\n    _ = message, kwargs\n",
        "def callback(value: object, /, *, context: object) -> None:\n    _ = value, context\n",
        "def callback(*values: object) -> None:\n    _ = values\n",
    ],
)
def test_reports_pure_parameter_markers(source: str) -> None:
    diagnostics = _check(source)

    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.WARNING


@pytest.mark.parametrize(
    "source",
    [
        "def on(event: str, callback: object) -> None:\n    pass\n",
        "def unsupported(event: str) -> None:\n    raise NotImplementedError\n",
        "def callback(_value: object) -> None:\n    return\n",
        "from typing import override\nclass Fake(Base):\n    @override\n    def on(self, event: str) -> None:\n        self.called = True\n",
    ],
)
def test_allows_explicit_stub_and_signature_contracts(source: str) -> None:
    assert _check(source) == []
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--no-cache", "--select", "ARG", "-"],
        input=source,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "source",
    [
        "def callback(cwd: Path) -> None:\n    _ = cwd.name\n",
        "def callback(cwd: Path) -> None:\n    _ = cwd, other\n",
        "def callback(cwd: Path) -> None:\n    _ = [cwd]\n",
        "def callback(cwd: Path) -> None:\n    cwd = Path('.')\n    _ = cwd\n",
    ],
)
def test_reports_other_discard_assignments_inside_functions(source: str) -> None:
    assert len(_check(source)) == 1


def test_exact_reasoned_suppression_is_respected() -> None:
    assert _check("_ = value  # sarj-noqa: SARJ452 — protocol fixture exercises the marker itself\n") == []


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("generated/client.py", "_ = value"),
        ("vendor/client.py", "_ = value"),
        ("app/client.py", "# This file is generated; do not edit.\n_ = value"),
    ],
)
def test_generated_and_vendored_files_are_excluded(path: str, source: str) -> None:
    assert _check(source, path) == []


def test_malformed_source_is_ignored() -> None:
    assert _check("_ = (") == []
