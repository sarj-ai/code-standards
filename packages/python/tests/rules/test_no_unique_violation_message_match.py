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
    assert [diagnostic.line for diagnostic in diagnostics] == [8]


@pytest.mark.parametrize(
    ("import_line", "caught", "field"),
    [
        ("from asyncpg import UniqueViolationError", "UniqueViolationError", "exc.constraint_name"),
        ("from asyncpg.exceptions import UniqueViolationError as Conflict", "Conflict", "exc.constraint_name"),
        ("import asyncpg", "asyncpg.UniqueViolationError", "exc.constraint_name"),
        ("import asyncpg.exceptions as db_errors", "db_errors.UniqueViolationError", "exc.constraint_name"),
    ],
)
def test_flags_supported_asyncpg_imports(import_line: str, caught: str, field: str) -> None:
    diagnostics = _check(f"""
        {import_line}
        try:
            save()
        except {caught} as exc:
            if 'duplicate' in str(exc):
                raise Duplicate from exc
    """)
    assert len(diagnostics) == 1
    assert field in diagnostics[0].message


@pytest.mark.parametrize(
    "caught",
    [
        "(UniqueViolation, RuntimeError)",
        "(RuntimeError, UniqueViolation)",
    ],
)
def test_ignores_mixed_exception_tuples(caught: str) -> None:
    assert (
        _check(f"""
        from psycopg.errors import UniqueViolation
        try:
            save()
        except {caught} as exc:
            if CONSTRAINT in str(exc):
                raise
    """)
        == []
    )


def test_flags_tuple_when_every_exception_is_a_supported_unique_violation() -> None:
    assert len(
        _check("""
        from psycopg.errors import UniqueViolation
        from psycopg2.errors import UniqueViolation as LegacyUniqueViolation
        try:
            save()
        except (UniqueViolation, LegacyUniqueViolation) as exc:
            if CONSTRAINT in str(exc):
                raise
    """)
    ) == 1


@pytest.mark.parametrize(
    "condition",
    [
        "CONSTRAINT in str(exc).lower()",
        "CONSTRAINT not in repr(exc).casefold().strip()",
        "str(exc) == EXPECTED_MESSAGE",
        "EXPECTED_MESSAGE != exc.pgerror",
        "exc.args[0].startswith(PREFIX)",
        "exc.diag.message_primary.endswith(SUFFIX)",
    ],
)
def test_flags_rendered_message_classification_forms(condition: str) -> None:
    assert len(
        _check(f"""
        from psycopg.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            if {condition}:
                raise Duplicate from exc
    """)
    ) == 1


@pytest.mark.parametrize(
    ("import_line", "condition"),
    [
        ("import re", "re.search(PATTERN, str(exc))"),
        ("import re as regex", "regex.fullmatch(PATTERN, str(exc))"),
        ("from re import match", "match(PATTERN, str(exc))"),
    ],
)
def test_flags_import_proven_regex_classification(import_line: str, condition: str) -> None:
    assert len(
        _check(f"""
        {import_line}
        from psycopg.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            if {condition}:
                return duplicate()
    """)
    ) == 1


def test_flags_straight_line_single_assignment_alias() -> None:
    assert len(
        _check("""
        from psycopg.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            message = str(exc).lower()
            if CONSTRAINT in message:
                raise Duplicate from exc
    """)
    ) == 1


@pytest.mark.parametrize(
    "source",
    [
        """
        from psycopg.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            if enabled:
                message = str(exc)
            if CONSTRAINT in message:
                raise
        """,
        """
        from psycopg.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            message = str(exc)
            message = normalize(message)
            if CONSTRAINT in message:
                raise
        """,
        """
        from psycopg.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            for exc in failures:
                pass
            if CONSTRAINT in str(exc):
                raise
        """,
        """
        from psycopg.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            values = [str(exc) for exc in failures]
            if CONSTRAINT in str(exc):
                raise
        """,
        """
        from psycopg.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            with context() as exc:
                pass
            if CONSTRAINT in str(exc):
                raise
        """,
        """
        from psycopg.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            try:
                recover()
            except RuntimeError as exc:
                pass
            if CONSTRAINT in str(exc):
                raise
        """,
    ],
)
def test_ignores_ambiguous_or_rebound_handler_values(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        """
        from psycopg import errors
        errors = app_errors
        try:
            save()
        except errors.UniqueViolation as exc:
            if CONSTRAINT in str(exc):
                raise
        """,
        """
        from psycopg.errors import UniqueViolation
        UniqueViolation = app_errors.UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            if CONSTRAINT in str(exc):
                raise
        """,
        """
        from psycopg import errors
        if use_app_errors:
            import app.errors as errors
        try:
            save()
        except errors.UniqueViolation as exc:
            if CONSTRAINT in str(exc):
                raise
        """,
        """
        from psycopg import errors
        def save_record(errors):
            try:
                save()
            except errors.UniqueViolation as exc:
                if CONSTRAINT in str(exc):
                    raise
        """,
        """
        from psycopg.errors import UniqueViolation
        def save_record():
            import app.errors.UniqueViolation as UniqueViolation
            try:
                save()
            except UniqueViolation as exc:
                if CONSTRAINT in str(exc):
                    raise
        """,
        """
        from sqlalchemy.exc import IntegrityError
        try:
            save()
        except IntegrityError as exc:
            if CONSTRAINT in str(exc):
                raise
        """,
        """
        from psycopg.errors import UniqueViolation
        from app.regex import search
        try:
            save()
        except UniqueViolation as exc:
            if search(PATTERN, str(exc)):
                raise
        """,
    ],
)
def test_requires_import_proven_exception_and_predicate_symbols(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "body",
    [
        "if str(exc) in EXPECTED_TEXT: raise Duplicate from exc",
        "if '\\n' in str(exc): sanitized = str(exc).replace('\\n', ' ')",
        "logger.warning('conflict: %s', str(exc))",
    ],
)
def test_ignores_nonclassification_message_usage(body: str) -> None:
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


@pytest.mark.parametrize(
    "field",
    [
        "exc.diag.constraint_name",
        "exc.constraint_name",
    ],
)
def test_accepts_structured_constraint_fields(field: str) -> None:
    assert (
        _check(f"""
        from asyncpg import UniqueViolationError
        try:
            save()
        except UniqueViolationError as exc:
            if {field} == CONSTRAINT:
                raise Duplicate from exc
    """)
        == []
    )


def test_nested_function_parameter_named_str_does_not_hide_builtin() -> None:
    assert len(
        _check("""
        from psycopg.errors import UniqueViolation
        try:
            save()
        except UniqueViolation as exc:
            def helper(str):
                return str
            if CONSTRAINT in str(exc):
                raise
    """)
    ) == 1


def test_enclosing_parameter_named_str_hides_builtin() -> None:
    assert (
        _check("""
        from psycopg.errors import UniqueViolation
        def save_record(str):
            try:
                save()
            except UniqueViolation as exc:
                if CONSTRAINT in str(exc):
                    raise
    """)
        == []
    )


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
