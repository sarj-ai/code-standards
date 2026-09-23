from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_delete_statement import NoDeleteStatement


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "app/service.py") -> list[Diagnostic]:
    return NoDeleteStatement().check(Path(path), textwrap.dedent(source))


_PUBLIC_EXAMPLES = NoDeleteStatement.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


@pytest.mark.parametrize(
    "statement",
    [
        "del value",
        "del record.attribute",
        "del values[index]",
        "del first, second",
        "del (first, values[index])",
    ],
)
def test_flags_every_delete_statement_once(statement: str) -> None:
    diagnostics = _check(statement)

    assert [(item.line, item.col, item.code, item.severity) for item in diagnostics] == [
        (1, 1, "SARJ442", Severity.ERROR)
    ]


def test_flags_nested_delete_statements_in_source_order() -> None:
    diagnostics = _check(
        """
        if enabled:
            del cache[key]
        else:
            del fallback
        """
    )

    assert [(item.line, item.col) for item in diagnostics] == [(3, 5), (5, 5)]


def test_exact_reasoned_suppression_is_respected() -> None:
    assert (
        _check("del cache[key]  # sarj-noqa: SARJ442 — MutableMapping contract requires __delitem__ semantics\n") == []
    )


def test_different_suppression_code_does_not_hide_finding() -> None:
    assert len(_check("del cache[key]  # sarj-noqa: SARJ999 — unrelated exception\n")) == 1


@pytest.mark.parametrize(
    "source",
    [
        "value = 'delete this text'",
        "# del cached_value",
        "def deliver(value: object) -> object:\n    return value",
        "filtered = {key: value for key, value in source.items() if key != removed_key}",
    ],
)
def test_ignores_non_delete_syntax(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("generated/client.py", "del self.additional_properties[key]"),
        ("vendor/client.py", "del self.additional_properties[key]"),
        ("app/client.py", "# This file is generated; do not edit.\ndel self.additional_properties[key]"),
    ],
)
def test_generated_and_vendored_files_are_excluded(path: str, source: str) -> None:
    assert _check(source, path) == []


def test_malformed_source_is_ignored() -> None:
    assert _check("del (") == []
