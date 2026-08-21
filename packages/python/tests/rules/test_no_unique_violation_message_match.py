from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_unique_violation_message_match import NoUniqueViolationMessageMatch


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "store.py"):
    return NoUniqueViolationMessageMatch().check(Path(path), dedent(source))


_PUBLIC_EXAMPLES = NoUniqueViolationMessageMatch.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoUniqueViolationMessageMatch().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    ("import_line", "caught"),
    [
        ("from psycopg.errors import UniqueViolation", "UniqueViolation"),
        ("from psycopg.errors import UniqueViolation as Conflict", "Conflict"),
        ("import psycopg as pg", "pg.errors.UniqueViolation"),
        ("import psycopg.errors as errors", "errors.UniqueViolation"),
        ("from psycopg import errors as db_errors", "db_errors.UniqueViolation"),
        ("from psycopg2 import errors", "errors.UniqueViolation"),
    ],
)
def test_flags_supported_psycopg_imports(import_line: str, caught: str) -> None:
    diagnostics = _check(f"""
        {import_line}
        try:
            save()
        except {caught} as exc:
            if CONSTRAINT not in str(exc):
                raise
    """)
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.ERROR


def test_flags_each_direct_comparison_in_source_order() -> None:
    diagnostics = _check("""
        from psycopg import errors
        try:
            save()
        except errors.UniqueViolation as exc:
            if FIRST in str(exc):
                recover()
            if SECOND not in str(exc):
                raise
    """)
    assert [diagnostic.line for diagnostic in diagnostics] == [6, 8]


@pytest.mark.parametrize(
    "body",
    [
        "if exc.diag.constraint_name == CONSTRAINT: recover()",
        "logger.warning('conflict: %s', str(exc))",
        "raise Duplicate from exc",
        "if CONSTRAINT in str(other): recover()",
    ],
)
def test_accepts_non_message_classification(body: str) -> None:
    assert (
        _check(f"""
        from psycopg.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            {body}
    """)
        == []
    )


def test_ignores_unrelated_same_named_exception() -> None:
    assert (
        _check("""
        from app.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            if CONSTRAINT in str(exc):
                recover()
    """)
        == []
    )


def test_ignores_nested_scope_inside_handler() -> None:
    assert (
        _check("""
        from psycopg.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            def delayed():
                return CONSTRAINT in str(exc)
            raise
    """)
        == []
    )


@pytest.mark.parametrize("path", ["test_store.py", "tests/store.py"])
def test_excludes_tests(path: str) -> None:
    assert _check("from psycopg.errors import UniqueViolation\n", path) == []


def test_excludes_generated_and_malformed_files() -> None:
    assert _check("# @generated\nfrom psycopg.errors import UniqueViolation\n") == []
    assert _check("from psycopg.errors import UniqueViolation\nif (") == []
