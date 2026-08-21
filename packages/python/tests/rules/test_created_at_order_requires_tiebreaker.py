from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import Diagnostic, Severity, is_suppressed
from sarj_python_lint.rules.created_at_order_requires_tiebreaker import (
    CreatedAtOrderRequiresTiebreaker,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "task_store.py") -> list[Diagnostic]:
    return CreatedAtOrderRequiresTiebreaker().check(Path(path), dedent(source))


def _kept(source: str, path: str = "task_store.py") -> list[Diagnostic]:
    normalized = dedent(source)
    diagnostics = CreatedAtOrderRequiresTiebreaker().check(Path(path), normalized)
    lines = normalized.splitlines()
    return [diagnostic for diagnostic in diagnostics if not is_suppressed(lines, diagnostic.line, diagnostic.code)]


_PUBLIC_EXAMPLES = CreatedAtOrderRequiresTiebreaker.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(CreatedAtOrderRequiresTiebreaker().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM task ORDER BY created_at",
        "SELECT id FROM task ORDER BY created_at ASC",
        "SELECT id FROM task ORDER BY created_at DESC NULLS LAST LIMIT 20",
        "SELECT id FROM task ORDER BY task.created_at DESC OFFSET 10",
        "SELECT id FROM task ORDER BY public.task.created_at ASC NULLS FIRST FETCH FIRST 5 ROWS ONLY",
        "SELECT id FROM task ORDER BY priority DESC, created_at DESC",
        "select id from task order    by created_at desc",
    ],
    ids=[
        "sole-default-direction",
        "sole-ascending",
        "descending-nulls-last",
        "qualified-before-offset",
        "multiply-qualified-before-fetch",
        "final-after-earlier-key",
        "case-and-whitespace-insensitive",
    ],
)
def test_reports_created_at_as_final_same_depth_order_item(query: str) -> None:
    findings = _check(f"QUERY = {query!r}\n")

    assert len(findings) == 1
    assert findings[0].code == "SARJ407"
    assert findings[0].severity is Severity.ERROR
    assert "tie-break key" in findings[0].message
    assert "`id`" in findings[0].message


def test_reports_nested_order_clause_at_its_own_depth() -> None:
    source = '''
        QUERY = """
            SELECT recent.id
            FROM (
                SELECT id
                FROM task
                ORDER BY created_at DESC
            ) AS recent
            ORDER BY recent.id
        """
    '''

    assert len(_check(source)) == 1


def test_reports_outer_order_clause_without_confusing_nested_commas() -> None:
    source = '''
        QUERY = """
            SELECT recent.id
            FROM (
                SELECT id
                FROM task
                ORDER BY created_at DESC, id DESC
            ) AS recent
            ORDER BY coalesce(recent.priority, 0), recent.created_at DESC
        """
    '''

    assert len(_check(source)) == 1


def test_reconstructs_static_concatenation_without_duplicate_diagnostics() -> None:
    source = 'QUERY = "SELECT id FROM task " + "ORDER BY created_at DESC"\n'

    findings = _check(source)

    assert len(findings) == 1
    assert (findings[0].line, findings[0].col) == (1, 9)


def test_reports_once_when_one_literal_has_multiple_unstable_order_clauses() -> None:
    source = '''
        QUERY = """
            WITH recent AS (
                SELECT id FROM task ORDER BY created_at DESC
            )
            SELECT id FROM recent ORDER BY created_at DESC
        """
    '''

    assert len(_check(source)) == 1


def test_reports_multiple_query_literals_in_source_order() -> None:
    source = (
        'FIRST = "SELECT id FROM task ORDER BY created_at DESC"\n'
        'SAFE = "SELECT id FROM task ORDER BY created_at DESC, id DESC"\n'
        'SECOND = "SELECT id FROM task ORDER BY task.created_at ASC"\n'
    )

    findings = _check(source)

    assert [(finding.line, finding.col) for finding in findings] == [(1, 9), (3, 10)]


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM task ORDER BY created_at DESC, id DESC",
        "SELECT id FROM task ORDER BY created_at, random()",
        "SELECT id FROM task ORDER BY priority, created_at DESC, lower(name)",
        "SELECT id FROM task ORDER BY id, updated_at",
        "SELECT id FROM task ORDER BY created_at_epoch DESC",
        "SELECT id FROM task ORDER BY date_trunc('second', created_at) DESC",
        "SELECT id FROM task ORDER BY coalesce(created_at, updated_at)",
        'SELECT id FROM task ORDER BY "created_at" DESC',
    ],
    ids=[
        "id-tiebreaker",
        "any-later-key-is-accepted",
        "created-at-has-later-expression",
        "different-final-column",
        "identifier-suffix",
        "created-at-inside-function",
        "created-at-inside-expression",
        "quoted-identifier-out-of-scope",
    ],
)
def test_accepts_later_keys_and_non_exact_created_at_expressions(query: str) -> None:
    assert _check(f"QUERY = {query!r}\n") == []


def test_same_depth_ignores_commas_inside_a_later_expression() -> None:
    source = 'QUERY = "SELECT id FROM task ORDER BY created_at DESC, coalesce(priority, 0)"\n'

    assert _check(source) == []


def test_same_depth_ignores_commas_inside_an_earlier_expression() -> None:
    source = 'QUERY = "SELECT id FROM task ORDER BY coalesce(priority, 0), created_at DESC"\n'

    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        'FRAGMENT = "ORDER BY created_at DESC"\n',
        'QUERY = prefix + "SELECT id FROM task ORDER BY created_at DESC"\n',
        'QUERY = "SELECT id FROM task ORDER BY created_at DESC" + suffix\n',
        'QUERY = f"SELECT {fields} FROM task ORDER BY created_at DESC"\n',
        'QUERY = f"SELECT id FROM task ORDER BY created_at DESC {suffix}"\n',
        'QUERY = b"SELECT id FROM task ORDER BY created_at DESC"\n',
    ],
    ids=[
        "non-select-fragment",
        "dynamic-prefix-concatenation",
        "dynamic-suffix-concatenation",
        "formatted-projection",
        "formatted-order-suffix",
        "bytes-literal",
    ],
)
def test_skips_sql_that_is_not_fully_reconstructable(source: str) -> None:
    assert _check(source) == []


def test_ignores_sql_tokens_inside_values_and_comments() -> None:
    source = '''
        QUERY = """
            SELECT id
            FROM task
            WHERE note = 'ORDER BY created_at DESC'
            -- ORDER BY created_at DESC
            /* ORDER BY created_at ASC */
            ORDER BY id
        """
    '''

    assert _check(source) == []


@pytest.mark.parametrize("path", ["task_store.py", "app/store.py", "app/stores/task.py"])
def test_reports_only_in_recognized_store_modules(path: str) -> None:
    source = 'QUERY = "SELECT id FROM task ORDER BY created_at DESC"\n'

    assert len(_check(source, path)) == 1


@pytest.mark.parametrize(
    "path",
    ["app/service.py", "app/storefront.py", "tests/task_store.py", "task_store_test.py", "app/stores/conftest.py"],
)
def test_skips_non_store_and_test_modules(path: str) -> None:
    source = 'QUERY = "SELECT id FROM task ORDER BY created_at DESC"\n'

    assert _check(source, path) == []


def test_skips_generated_and_malformed_source() -> None:
    query = 'QUERY = "SELECT id FROM task ORDER BY created_at DESC"\n'

    assert _check(f"# generated by schema compiler\n{query}") == []
    assert _check("class Broken(") == []


@pytest.mark.parametrize(
    "source",
    [
        'QUERY = "SELECT id FROM task ORDER BY created_at DESC"  # sarj-noqa\n',
        'QUERY = "SELECT id FROM task ORDER BY created_at DESC"  # sarj-noqa: SARJ407\n',
        'QUERY = "SELECT id FROM task ORDER BY created_at DESC"  # sarj-noqa: SARJ025, SARJ407\n',
    ],
    ids=["bare", "exact-code", "multiple-codes"],
)
def test_local_suppression_can_remove_the_warning(source: str) -> None:
    assert _kept(source) == []


def test_unrelated_suppression_code_does_not_remove_the_warning() -> None:
    source = 'QUERY = "SELECT id FROM task ORDER BY created_at DESC"  # sarj-noqa: SARJ025\n'

    assert len(_kept(source)) == 1
