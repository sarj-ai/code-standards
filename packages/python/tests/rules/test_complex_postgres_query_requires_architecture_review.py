from pathlib import Path

import pytest

from sarj_python_lint.rule_base import Diagnostic, RuleExample, Severity, is_suppressed
from sarj_python_lint.rules.complex_postgres_query_requires_architecture_review import (
    ComplexPostgresQueryRequiresArchitectureReview,
)


def _check(source: str, filename: str = "call_store.py") -> list[Diagnostic]:
    return ComplexPostgresQueryRequiresArchitectureReview().check(Path(filename), source)


_PUBLIC_EXAMPLES = ComplexPostgresQueryRequiresArchitectureReview.public_examples()


@pytest.mark.parametrize(
    "example",
    _PUBLIC_EXAMPLES,
    ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES),
)
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def test_flags_motivating_fair_queue_claim_once() -> None:
    source = '''import psycopg
from psycopg.sql import SQL

async def claim(cur, fields):
    await cur.execute(
        SQL("""
        SELECT {fields}
        FROM call AS due
        JOIN (
            SELECT ranked.id, ranked.org_rank FROM (
                SELECT due.id, ROW_NUMBER() OVER (
                    PARTITION BY due.organization_id
                    ORDER BY due.scheduled_at ASC, due.id ASC
                ) AS org_rank
                FROM call AS due
                WHERE due.status = %s
                  AND NOT EXISTS (
                    SELECT 1 FROM batch_call
                    JOIN batch ON batch.id = batch_call.batch_id
                    WHERE batch_call.id = due.batch_call_id
                  )
            ) AS ranked WHERE ranked.org_rank <= %s
        ) AS ranked ON ranked.id = due.id
        ORDER BY ranked.org_rank ASC, due.scheduled_at ASC, due.id ASC
        LIMIT %s
        FOR UPDATE OF due SKIP LOCKED
        """).format(fields=SQL(fields))
    )
'''
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.WARNING
    assert "derived query" in diagnostics[0].message
    assert "query-plan" not in diagnostics[0].message.lower()


def test_flags_derived_select_in_join() -> None:
    source = '''import asyncpg
connection.fetch("""
SELECT account.id
FROM account
JOIN (SELECT account_id, COUNT(*) FROM membership WHERE active GROUP BY account_id) AS active_member
  ON active_member.account_id = account.id
""")
'''
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rank FROM event) AS ranked",
        "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) AS totals",
        "SELECT * FROM (SELECT org_id FROM a UNION ALL SELECT org_id FROM b) AS orgs",
        "SELECT * FROM (SELECT * FROM (SELECT id FROM event) AS inner_event) AS outer_event",
    ],
)
def test_flags_complex_from_derived_stage(query: str) -> None:
    source = f'import psycopg\ncursor.execute("{query}")\n'
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM (SELECT id FROM event WHERE id = %s) AS bounded",
        "SELECT account.id FROM account JOIN (SELECT account_id FROM membership WHERE active) active ON TRUE",
        "WITH bounded AS (SELECT id FROM event WHERE id = %s) SELECT * FROM bounded",
        "SELECT id FROM event WHERE EXISTS (SELECT 1 FROM tag WHERE tag.event_id = event.id)",
        "SELECT id FROM event WHERE id IN (SELECT event_id FROM tag)",
        "SELECT id, (SELECT name FROM org WHERE org.id = event.org_id) AS org_name FROM event",
        "SELECT * FROM event JOIN LATERAL (SELECT id FROM tag WHERE tag.event_id = event.id) AS tag ON TRUE",
    ],
)
def test_allows_non_complex_or_non_relation_subqueries(query: str) -> None:
    source = f'import psycopg\ncursor.execute("{query}")\n'
    assert _check(source) == []


def test_exists_containing_simple_derived_stage_is_ignored() -> None:
    source = '''import psycopg
cursor.execute("""
SELECT id FROM event
WHERE EXISTS (
    SELECT 1
    FROM (SELECT id FROM tag WHERE active) AS active_tag
    WHERE active_tag.id = event.tag_id
)
""")
'''
    assert _check(source) == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM event WHERE EXISTS (SELECT 1 FROM (SELECT tag_id, COUNT(*) FROM tag GROUP BY tag_id) t)",
        "SELECT id FROM event WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id) n FROM tag) t)",
        "SELECT (SELECT COUNT(*) FROM (SELECT org_id, COUNT(*) FROM tag GROUP BY org_id) t) FROM event",
        "SELECT * FROM event JOIN LATERAL (SELECT org_id, COUNT(*) FROM tag GROUP BY org_id) t ON TRUE",
    ],
)
def test_complex_derived_stages_in_excluded_subquery_contexts_are_ignored(query: str) -> None:
    source = f'import psycopg\ncursor.execute("{query}")\n'
    assert _check(source) == []


def test_excluded_subquery_does_not_make_an_outer_derived_relation_complex() -> None:
    source = '''import psycopg
cursor.execute("""
SELECT * FROM (
    SELECT id FROM event
    WHERE EXISTS (SELECT ROW_NUMBER() OVER (ORDER BY id) FROM tag)
) outer_event
""")
'''
    assert _check(source) == []


def test_detects_static_concatenation_once() -> None:
    source = """import psycopg
cursor.execute(
    "SELECT event.id FROM event "
    + "JOIN (SELECT event_id, COUNT(*) FROM tag GROUP BY event_id) AS tagged ON tagged.event_id = event.id"
)
"""
    assert len(_check(source)) == 1


def test_detects_fstring_with_value_hole_once() -> None:
    source = """import psycopg
cursor.execute(f"SELECT event.id FROM event JOIN (SELECT event_id, COUNT(*) FROM tag WHERE kind = {kind} GROUP BY event_id) tagged ON TRUE")
"""
    assert len(_check(source)) == 1


def test_psycopg_format_identifier_is_normalized() -> None:
    source = """import psycopg
from psycopg.sql import SQL
cursor.execute(SQL("SELECT {fields} FROM event JOIN (SELECT event_id, COUNT(*) FROM tag GROUP BY event_id) tagged ON TRUE").format(
    fields=SQL("event.id")
))
"""
    assert len(_check(source)) == 1


def test_query_sink_is_executable_context() -> None:
    source = """import psycopg
cursor.execute("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals")
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize("sink", ["execute", "executemany", "fetch", "fetchrow", "fetchval", "prepare"])
def test_recognizes_database_query_sinks(sink: str) -> None:
    source = (
        "import asyncpg\n"  # ruff:ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
        f'connection.{sink}("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals")\n'
    )
    assert len(_check(source)) == 1


def test_recognizes_query_keyword_and_arbitrary_local_binding() -> None:
    source = """import psycopg

def claim(cursor):
    candidate: str = "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"
    cursor.execute(query=candidate)
"""
    assert len(_check(source)) == 1


def test_one_binding_used_by_multiple_sinks_emits_once() -> None:
    source = """import psycopg

def claim(cursor):
    candidate = "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"
    cursor.execute(candidate)
    cursor.execute(candidate)
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "body",
    [
        'QUERY_EXAMPLE = "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"',
        'def sql(value):\n    return value\nsql("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals")',
        'formatter.text("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals")',
        'cursor.execute(params, "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals")',
    ],
)
def test_names_and_non_query_arguments_do_not_prove_execution(body: str) -> None:
    assert _check(f"import psycopg\n{body}\n") == []


def test_rebound_or_conditional_bindings_abstain() -> None:
    rebound = """import psycopg
def claim(cursor):
    candidate = "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"
    candidate = fallback
    cursor.execute(candidate)
"""
    conditional = """import psycopg
def claim(cursor, ready):
    if ready:
        candidate = "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"
        cursor.execute(candidate)
"""
    assert _check(rebound) == []
    assert _check(conditional) == []


def test_cross_scope_binding_abstains() -> None:
    source = """import psycopg
CANDIDATE = "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"

def claim(cursor):
    cursor.execute(CANDIDATE)
"""
    assert _check(source) == []


def test_dynamic_hole_cannot_supply_relational_structure() -> None:
    source = """import psycopg
cursor.execute(f"SELECT id FROM event {derived_relation}")
"""
    assert _check(source) == []


def test_asyncpg_command_keyword_is_query_context() -> None:
    source = """import asyncpg
connection.executemany(
    command="SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals",
    args=[],
)
"""
    assert len(_check(source)) == 1


def test_same_line_preceding_binding_is_followed() -> None:
    source = """import psycopg
def claim(cursor):
    candidate = "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"; cursor.execute(candidate)
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "expression",
    [
        'render("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals")',
        'choose("SELECT 1", "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals")',
        '"SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals" if enabled else "SELECT 1"',
    ],
)
def test_unknown_query_composition_abstains(expression: str) -> None:
    assert _check(f"import psycopg\ncursor.execute({expression})\n") == []


@pytest.mark.parametrize(
    "rebind",
    [
        "import json as candidate",
        "def candidate():\n    pass",
        "class candidate:\n    pass",
        "del candidate",
        "match value:\n    case candidate:\n        pass",
    ],
)
def test_non_assignment_rebinding_abstains(rebind: str) -> None:
    source = f"""import psycopg
candidate = "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"
{rebind}
cursor.execute(candidate)
"""  # ruff:ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert _check(source) == []


def test_unrelated_execute_receiver_abstains() -> None:
    source = """import psycopg
renderer.execute("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals")
"""
    assert _check(source) == []


@pytest.mark.parametrize("receiver", ["con", "acur", "session", "get_connection()"])
def test_conventional_database_receiver_variants_are_supported(receiver: str) -> None:
    source = (
        "import asyncpg\n"  # ruff:ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
        f'{receiver}.execute("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals")\n'
    )
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "prefix",
    [
        "import psycopg",
        "from psycopg.sql import SQL\nSQL = lambda value: 'SELECT 1'",
    ],
)
def test_unproven_or_rebound_sql_constructor_abstains(prefix: str) -> None:
    source = (
        f'{prefix}\ncursor.execute(SQL("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"))\n'  # ruff:ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    )
    assert _check(source) == []


def test_wildcard_import_makes_local_binding_ambiguous() -> None:
    source = """import psycopg
from query_helpers import *
candidate = "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"
cursor.execute(candidate)
"""
    assert _check(source) == []


def test_unrelated_nested_constructor_shadow_does_not_hide_module_import() -> None:
    source = """from psycopg.sql import SQL

def helper():
    SQL = lambda value: value
    return SQL

cursor.execute(SQL("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"))
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize("statement", ["from . import psycopg", "from .psycopg import helper"])
def test_relative_import_does_not_prove_postgres_ownership(statement: str) -> None:
    source = (
        f'{statement}\ncursor.execute("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals")\n'  # ruff:ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    )
    assert _check(source) == []


@pytest.mark.parametrize(
    "statement",
    [
        'MESSAGE = "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"',
        'raise ValueError("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals")',
        'description = "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"',
    ],
)
def test_query_looking_prose_is_ignored(statement: str) -> None:
    assert _check(f"import psycopg\n{statement}\n") == []


def test_multiple_complex_relations_in_one_literal_emit_one_diagnostic() -> None:
    source = '''import psycopg
cursor.execute("""
SELECT event.id
FROM event
JOIN (SELECT event_id, COUNT(*) FROM tag GROUP BY event_id) AS tagged ON tagged.event_id = event.id
JOIN (SELECT event_id, COUNT(*) FROM audit GROUP BY event_id) AS audited ON audited.event_id = event.id
""")
'''
    assert len(_check(source)) == 1


def test_multiple_literals_emit_sorted_diagnostics() -> None:
    source = """import psycopg
cursor.execute("SELECT event.id FROM event JOIN (SELECT event_id, COUNT(*) FROM tag GROUP BY event_id) tagged ON TRUE")
cursor.execute("SELECT event.id FROM event JOIN (SELECT event_id, COUNT(*) FROM audit GROUP BY event_id) audited ON TRUE")
"""
    diagnostics = _check(source)
    assert [(diagnostic.line, diagnostic.col) for diagnostic in diagnostics] == [(2, 16), (3, 16)]


@pytest.mark.parametrize(
    ("filename", "source"),
    [
        (
            "service.py",
            'import psycopg\ncursor.execute("SELECT * FROM event JOIN (SELECT event_id FROM tag) tagged ON TRUE")\n',
        ),
        (
            "test_event_store.py",
            'import psycopg\ncursor.execute("SELECT * FROM event JOIN (SELECT event_id FROM tag) tagged ON TRUE")\n',
        ),
        (
            "event_store.py",
            '# Code generated by sqlc. DO NOT EDIT.\nimport psycopg\ncursor.execute("SELECT * FROM event JOIN (SELECT id FROM tag) t ON TRUE")\n',
        ),
        (
            "event_store.py",
            'import sqlite3\ncursor.execute("SELECT * FROM event JOIN (SELECT event_id FROM tag) tagged ON TRUE")\n',
        ),
        (
            "event_store.py",
            'import clickhouse_connect\nclient.execute("SELECT * FROM event JOIN (SELECT event_id FROM tag) tagged ON TRUE")\n',
        ),
        (
            "event_store.py",
            'from google.cloud import bigquery\nclient.query("SELECT * FROM `p.d.event` JOIN (SELECT event_id FROM `p.d.tag`) t ON TRUE")\n',
        ),
        (
            "event_store.py",
            '# PostgreSQL is used elsewhere\nimport sqlite3\ncursor.execute("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) t")\n',
        ),
        (
            "event_store.py",
            'import psycopg\nimport sqlite3\ncursor.execute("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) t")\n',
        ),
        (
            "event_store.py",
            'from app.settings import postgres\ncursor.execute("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) t")\n',
        ),
        (
            "event_store.py",
            'from app.postgres.models import Thing\ncursor.execute("SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) t")\n',
        ),
    ],
)
def test_excludes_unsupported_owners(filename: str, source: str) -> None:
    assert _check(source, filename) == []


def test_sql_in_docstring_is_not_executable() -> None:
    source = '''import psycopg

def explain() -> None:
    """Avoid SELECT * FROM event JOIN (SELECT event_id FROM tag) tagged ON TRUE."""
'''
    assert _check(source) == []


def test_psycopg_pool_import_is_postgres_ownership() -> None:
    source = """from psycopg_pool import AsyncConnectionPool
QUERY = "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals"
cursor.execute(QUERY)
"""
    assert len(_check(source)) == 1


def test_sql_keywords_in_comments_and_literals_do_not_create_structure() -> None:
    source = '''import psycopg
cursor.execute("""
SELECT id FROM event
-- JOIN (SELECT event_id FROM tag) tagged ON TRUE
WHERE note = 'JOIN (SELECT id FROM hidden)'
""")
'''
    assert _check(source) == []


def test_malformed_python_is_ignored() -> None:
    source = 'import psycopg\nQUERY = "SELECT * FROM event JOIN (SELECT id FROM tag) t ON TRUE"\ndef (:\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM event JOIN (SELECT id FROM tag",
        "SELECT * FROM (SELECT $$unterminated",
        "SELECT * FROM (SELECT E'unterminated",
        "SELECT * FROM (SELECT /* unterminated",
    ],
)
def test_malformed_sql_is_ignored(query: str) -> None:
    source = f'import psycopg\ncursor.execute("{query}")\n'
    assert _check(source) == []


def test_reasoned_exact_code_suppression_is_supported() -> None:
    source = (
        "import psycopg\n"
        'QUERY = "SELECT * FROM event JOIN (SELECT event_id, COUNT(*) FROM tag GROUP BY event_id) tagged ON TRUE"  '
        "# sarj-noqa: SARJ437 -- bounded plan uses an index-only scan\n"
        "cursor.execute(QUERY)\n"
    )
    (diagnostic,) = _check(source)
    assert is_suppressed(source.splitlines(), diagnostic.line, diagnostic.code)


def test_diagnostic_metadata() -> None:
    source = (
        "import psycopg\n"
        'cursor.execute("SELECT * FROM event JOIN (SELECT event_id, COUNT(*) FROM tag GROUP BY event_id) tagged ON TRUE")\n'
    )
    (diagnostic,) = _check(source)
    assert diagnostic.code == "SARJ437"
    assert diagnostic.path == Path("call_store.py")
    assert (diagnostic.line, diagnostic.col) == (2, 16)
    assert diagnostic.severity is Severity.WARNING
    assert "review bounds, ordering, and locks" in diagnostic.message
