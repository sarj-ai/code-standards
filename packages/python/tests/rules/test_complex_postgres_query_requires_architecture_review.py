from pathlib import Path

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.rule_base import Diagnostic, RuleExample, Severity, is_suppressed
from sarj_python_lint.rules.complex_postgres_query_requires_architecture_review import (
    ComplexPostgresQueryRequiresArchitectureReview,
)
from sarj_python_lint.rules.no_analytical_aggregation_in_postgres_store import NoAnalyticalAggregationInPostgresStore


def _check(source: str, filename: str = "call_store.py") -> list[Diagnostic]:
    return ComplexPostgresQueryRequiresArchitectureReview().check(Path(filename), source)


_PUBLIC_EXAMPLES = ComplexPostgresQueryRequiresArchitectureReview.public_examples()


@pytest.mark.parametrize(
    "query",
    [
        "SELECT a.id FROM a INNER JOIN b ON TRUE LEFT JOIN c ON TRUE CROSS JOIN d NATURAL JOIN e",
        "SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE JOIN f ON TRUE",
        "WITH roots AS (SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE) SELECT id FROM roots",
        "SELECT a.id FROM a WHERE EXISTS (SELECT b.id FROM b JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE JOIN f ON TRUE)",
        "SELECT a.id FROM a UNION ALL SELECT b.id FROM b JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE JOIN f ON TRUE",
        "SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN (SELECT e.id FROM e GROUP BY e.id) e ON TRUE",
    ],
    ids=("mixed-root", "five-joins", "cte", "exists", "union-branch", "overlapping-derived-stage"),
)
def test_multiple_joins_merit_one_review_warning(query: str) -> None:
    diagnostics = _check(f'import psycopg\ncursor.execute("{query}")\n')
    assert len(diagnostics) == 1
    assert diagnostics[0].severity is Severity.WARNING
    assert "4+ explicit JOINs" in diagnostics[0].message
    assert "write-time" in diagnostics[0].message
    assert "read-time reconstruction" in diagnostics[0].message
    assert "Syntax alone does not establish runtime cost or datastore placement" in diagnostics[0].message


@pytest.mark.parametrize(
    "query",
    [
        "SELECT a.id FROM a JOIN b ON b.id = a.id",
        "SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE",
        "SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE WHERE EXISTS (SELECT e.id FROM e JOIN f ON TRUE JOIN g ON TRUE JOIN h ON TRUE)",
        "WITH roots AS (SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE) SELECT roots.id FROM roots JOIN e ON TRUE JOIN f ON TRUE JOIN g ON TRUE",
        "SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE UNION ALL SELECT e.id FROM e JOIN f ON TRUE JOIN g ON TRUE JOIN h ON TRUE",
        "SELECT 'JOIN JOIN JOIN JOIN' FROM a JOIN b ON TRUE /* JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE */",
        "SELECT a.id FROM a JOIN JOIN",
    ],
    ids=(
        "one-join",
        "three-joins",
        "separate-nested",
        "separate-cte",
        "separate-union",
        "noise",
        "malformed",
    ),
)
def test_join_count_is_per_select_and_ignores_noise(query: str) -> None:
    assert _check(f'import psycopg\ncursor.execute("{query}")\n') == []


def test_multi_join_review_uses_postgres_execution_not_store_filename() -> None:
    source = (
        'from psycopg_pool import AsyncConnectionPool\ncursor.execute("SELECT a.id FROM a JOIN b ON TRUE '
        'JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE")\n'
    )
    assert len(_check(source, "simulated_call.py")) == 1
    assert _check(source, "tests/test_simulated_call.py") == []
    assert _check(source.replace("psycopg_pool", "clickhouse_connect"), "simulated_call.py") == []


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
JOIN (SELECT account_id, COUNT(*) FROM membership JOIN role ON role.id = membership.role_id WHERE active GROUP BY account_id) AS active_member
  ON active_member.account_id = account.id
""")
'''
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM (SELECT event.id, ROW_NUMBER() OVER (ORDER BY event.id) AS rank FROM event JOIN tag ON tag.event_id = event.id) AS ranked",
        "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) AS totals",
        "SELECT * FROM (SELECT org_id FROM a GROUP BY org_id UNION ALL SELECT org_id FROM b) AS orgs",
        "SELECT * FROM (SELECT * FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id) n FROM event) AS inner_event) AS outer_event",
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
        "SELECT id FROM event WHERE EXISTS (SELECT 1 FROM (SELECT tag_id, COUNT(*) FROM tag JOIN kind ON kind.id = tag.kind_id GROUP BY tag_id) t)",
        "SELECT id FROM event WHERE id IN (SELECT id FROM (SELECT tag.id, ROW_NUMBER() OVER (ORDER BY tag.id) n FROM tag JOIN kind ON kind.id = tag.kind_id) t)",
        "SELECT (SELECT COUNT(*) FROM (SELECT org_id, COUNT(*) FROM tag JOIN kind ON kind.id = tag.kind_id GROUP BY org_id) t) FROM event",
        "SELECT * FROM event JOIN LATERAL (SELECT org_id, COUNT(*) FROM tag JOIN kind ON kind.id = tag.kind_id GROUP BY org_id) t ON TRUE",
    ],
)
def test_complex_derived_stages_are_reviewed_in_every_subquery_context(query: str) -> None:
    source = f'import psycopg\ncursor.execute("{query}")\n'
    assert len(_check(source)) == 1


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
    + "JOIN (SELECT event_id, COUNT(*) FROM tag JOIN kind ON kind.id = tag.kind_id GROUP BY event_id) AS tagged ON tagged.event_id = event.id"
)
"""
    assert len(_check(source)) == 1


def test_detects_fstring_with_value_hole_once() -> None:
    source = """import psycopg
cursor.execute(f"SELECT event.id FROM event JOIN (SELECT event_id, COUNT(*) FROM tag JOIN event ON event.id = tag.event_id WHERE kind = {kind} GROUP BY event_id) tagged ON TRUE")
"""
    assert len(_check(source)) == 1


def test_psycopg_format_identifier_is_normalized() -> None:
    source = """import psycopg
from psycopg.sql import SQL
cursor.execute(SQL("SELECT {fields} FROM event JOIN (SELECT event_id, COUNT(*) FROM tag JOIN kind ON kind.id = tag.kind_id GROUP BY event_id) tagged ON TRUE").format(
    fields=SQL("event.id")
))
"""
    assert len(_check(source)) == 1


def test_query_sink_is_executable_context() -> None:
    source = """import psycopg
cursor.execute("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals")
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize("sink", ["execute", "executemany", "fetch", "fetchrow", "fetchval", "prepare"])
def test_recognizes_database_query_sinks(sink: str) -> None:
    source = (
        "import asyncpg\n"  # ruff:ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
        f'connection.{sink}("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals")\n'
    )
    assert len(_check(source)) == 1


def test_recognizes_query_keyword_and_arbitrary_local_binding() -> None:
    source = """import psycopg

def claim(cursor):
    candidate: str = "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"
    cursor.execute(query=candidate)
"""
    assert len(_check(source)) == 1


def test_one_binding_used_by_multiple_sinks_emits_once() -> None:
    source = """import psycopg

def claim(cursor):
    candidate = "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"
    cursor.execute(candidate)
    cursor.execute(candidate)
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "body",
    [
        'QUERY_EXAMPLE = "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"',
        'def sql(value):\n    return value\nsql("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals")',
        'formatter.text("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals")',
        'cursor.execute(params, "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals")',
    ],
)
def test_names_and_non_query_arguments_do_not_prove_execution(body: str) -> None:
    assert _check(f"import psycopg\n{body}\n") == []


def test_rebound_or_conditional_bindings_abstain() -> None:
    rebound = """import psycopg
def claim(cursor):
    candidate = "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"
    candidate = fallback
    cursor.execute(candidate)
"""
    conditional = """import psycopg
def claim(cursor, ready):
    if ready:
        candidate = "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"
        cursor.execute(candidate)
"""
    assert _check(rebound) == []
    assert _check(conditional) == []


def test_cross_scope_binding_abstains() -> None:
    source = """import psycopg
CANDIDATE = "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"

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
    command="SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals",
    args=[],
)
"""
    assert len(_check(source)) == 1


def test_same_line_preceding_binding_is_followed() -> None:
    source = """import psycopg
def claim(cursor):
    candidate = "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"; cursor.execute(candidate)
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "expression",
    [
        'render("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals")',
        'choose("SELECT 1", "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals")',
        '"SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals" if enabled else "SELECT 1"',
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
candidate = "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"
{rebind}
cursor.execute(candidate)
"""  # ruff:ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert _check(source) == []


def test_unrelated_execute_receiver_abstains() -> None:
    source = """import psycopg
renderer.execute("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals")
"""
    assert _check(source) == []


@pytest.mark.parametrize("receiver", ["con", "acur", "session", "get_connection()"])
def test_conventional_database_receiver_variants_are_supported(receiver: str) -> None:
    source = (
        "import asyncpg\n"  # ruff:ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
        f'{receiver}.execute("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals")\n'
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
    source = f'{prefix}\ncursor.execute(SQL("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"))\n'  # ruff:ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert _check(source) == []


def test_wildcard_import_makes_local_binding_ambiguous() -> None:
    source = """import psycopg
from query_helpers import *
candidate = "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"
cursor.execute(candidate)
"""
    assert _check(source) == []


def test_unrelated_nested_constructor_shadow_does_not_hide_module_import() -> None:
    source = """from psycopg.sql import SQL

def helper():
    SQL = lambda value: value
    return SQL

cursor.execute(SQL("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"))
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize("statement", ["from . import psycopg", "from .psycopg import helper"])
def test_relative_import_does_not_prove_postgres_ownership(statement: str) -> None:
    source = f'{statement}\ncursor.execute("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals")\n'  # ruff:ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert _check(source) == []


@pytest.mark.parametrize(
    "statement",
    [
        'MESSAGE = "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"',
        'raise ValueError("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals")',
        'description = "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"',
    ],
)
def test_query_looking_prose_is_ignored(statement: str) -> None:
    assert _check(f"import psycopg\n{statement}\n") == []


def test_multiple_complex_relations_in_one_literal_emit_one_diagnostic() -> None:
    source = '''import psycopg
cursor.execute("""
SELECT event.id
FROM event
JOIN (SELECT event_id, COUNT(*) FROM tag JOIN kind ON kind.id = tag.kind_id GROUP BY event_id) AS tagged ON tagged.event_id = event.id
JOIN (SELECT event_id, COUNT(*) FROM audit JOIN kind ON kind.id = audit.kind_id GROUP BY event_id) AS audited ON audited.event_id = event.id
""")
'''
    assert len(_check(source)) == 1


def test_flags_four_ordinary_joins() -> None:
    source = '''import psycopg
cursor.execute("""
SELECT event.id FROM event
JOIN account ON account.id = event.account_id
JOIN organization ON organization.id = account.organization_id
JOIN region ON region.id = organization.region_id
JOIN country ON country.id = region.country_id
""")
'''
    [diagnostic] = _check(source)
    assert "4 JOINs" in diagnostic.message


def test_three_ordinary_joins_alone_are_allowed() -> None:
    source = '''import psycopg
cursor.execute("""
SELECT event.id FROM event
JOIN account ON account.id = event.account_id
JOIN organization ON organization.id = account.organization_id
JOIN region ON region.id = organization.region_id
""")
'''
    assert _check(source) == []


def test_flags_six_named_or_nested_query_stages() -> None:
    source = '''import psycopg
cursor.execute("""
WITH a AS (SELECT id FROM event),
b AS (SELECT id FROM a),
c AS (SELECT id FROM b),
d AS (SELECT id FROM c),
e AS (SELECT id FROM d)
SELECT id FROM e WHERE EXISTS (SELECT 1 FROM tag WHERE tag.event_id = e.id)
""")
'''
    [diagnostic] = _check(source)
    assert "6 CTE/subquery stages" in diagnostic.message


def test_flags_wide_joined_projection_but_not_wide_hydration() -> None:
    columns = ", ".join(f"event.column_{position}" for position in range(25))
    joined = (
        "import psycopg\n"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
        f'cursor.execute("SELECT {columns} FROM event JOIN account ON TRUE JOIN organization ON TRUE")\n'
    )
    hydration = f'import psycopg\ncursor.execute("SELECT {columns} FROM event")\n'  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert "25 projected expressions" in _check(joined)[0].message
    assert _check(hydration) == []


def test_mixed_backend_import_does_not_hide_postgres_query() -> None:
    source = """import psycopg
import clickhouse_connect
cursor.execute("SELECT event.id FROM event JOIN a ON TRUE JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE")
"""
    assert len(_check(source)) == 1


def test_multiple_literals_emit_sorted_diagnostics() -> None:
    source = """import psycopg
cursor.execute("SELECT event.id FROM event JOIN (SELECT event_id, COUNT(*) FROM tag JOIN kind ON kind.id = tag.kind_id GROUP BY event_id) tagged ON TRUE")
cursor.execute("SELECT event.id FROM event JOIN (SELECT event_id, COUNT(*) FROM audit JOIN kind ON kind.id = audit.kind_id GROUP BY event_id) audited ON TRUE")
"""
    diagnostics = _check(source)
    assert [(diagnostic.line, diagnostic.col) for diagnostic in diagnostics] == [(2, 16), (3, 16)]


@pytest.mark.parametrize(
    ("filename", "source"),
    [
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
            '# PostgreSQL is used elsewhere\nimport sqlite3\ncursor.execute("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) t")\n',
        ),
        (
            "event_store.py",
            'import psycopg\nimport sqlite3\ncursor.execute("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) t")\n',
        ),
        (
            "event_store.py",
            'from app.settings import postgres\ncursor.execute("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) t")\n',
        ),
        (
            "event_store.py",
            'from app.postgres.models import Thing\ncursor.execute("SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) t")\n',
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
QUERY = "SELECT * FROM (SELECT event.org_id, COUNT(*) FROM event JOIN owner ON owner.id = event.org_id GROUP BY event.org_id) totals"
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
        'QUERY = "SELECT * FROM event JOIN (SELECT event_id, COUNT(*) FROM tag JOIN kind ON kind.id = tag.kind_id GROUP BY event_id) tagged ON TRUE"  '
        "# sarj-noqa: SARJ437 -- bounded plan uses an index-only scan\n"
        "cursor.execute(QUERY)\n"
    )
    (diagnostic,) = _check(source)
    assert is_suppressed(source.splitlines(), diagnostic.line, diagnostic.code)


def test_diagnostic_metadata() -> None:
    source = (
        "import psycopg\n"
        'cursor.execute("SELECT * FROM event JOIN (SELECT event_id, COUNT(*) FROM tag JOIN kind ON kind.id = tag.kind_id GROUP BY event_id) tagged ON TRUE")\n'
    )
    (diagnostic,) = _check(source)
    assert diagnostic.code == "SARJ437"
    assert diagnostic.path == Path("call_store.py")
    assert (diagnostic.line, diagnostic.col) == (2, 16)
    assert diagnostic.severity is Severity.WARNING
    assert "review bounds, ordering, and locks" in diagnostic.message


@pytest.mark.parametrize("filename", ["store.py", "dispatch_evidence.py", "service.py"])
@pytest.mark.parametrize(
    "query",
    [
        "WITH evidence AS (SELECT a.id FROM a JOIN LATERAL (SELECT b.id, COUNT(*) FROM b JOIN c ON c.id = b.id GROUP BY b.id) t ON TRUE) SELECT COUNT(*) FROM evidence",
        "WITH totals AS (SELECT * FROM a JOIN (SELECT b.id, COUNT(*) FROM b JOIN c ON c.id = b.id GROUP BY b.id) b ON TRUE) SELECT * FROM totals",
        "SELECT a.id FROM a, b, c, d, e",
        "SELECT a.id FROM a, b JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE",
        "INSERT INTO result SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE",
        "UPDATE result SET id = evidence.id FROM (SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE) evidence",
    ],
    ids=[
        "lateral-in-cte",
        "derived-in-cte",
        "comma-joins",
        "mixed-comma-joins",
        "insert-select",
        "update-select",
    ],
)
def test_extended_shapes_do_not_depend_on_filename(filename: str, query: str) -> None:
    [diagnostic] = _check(f"import psycopg\ncursor.execute({query!r})\n", filename)
    assert diagnostic.code == "SARJ437"
    assert diagnostic.severity is Severity.WARNING


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM a JOIN LATERAL (SELECT COUNT(*) FROM b WHERE b.id = a.id) totals ON TRUE",
        "SELECT COUNT(*), MIN(id), MAX(id), SUM(id), AVG(id) FROM event",
        "SELECT COUNT(*) FILTER (WHERE a), COUNT(*) FILTER (WHERE b), COUNT(*) FILTER (WHERE c) FROM event",
        "SELECT (SELECT id FROM a), (SELECT id FROM b) FROM event",
        "SELECT ROW_NUMBER() OVER (ORDER BY a), RANK() OVER (ORDER BY b) FROM event",
        "SELECT * FROM event JOIN LATERAL (SELECT id FROM tag WHERE tag.event_id = event.id ORDER BY id LIMIT 1) t ON TRUE",
        "SELECT a.id FROM a, b, c, d",
        "WITH a AS (SELECT COUNT(*) n FROM event) SELECT SUM(n) FROM a",
        "INSERT INTO result SELECT id FROM event WHERE id = %s",
        "SELECT * FROM event JOIN LATERAL jsonb_array_elements(event.tags) tag ON TRUE",
    ],
    ids=[
        "lateral-count",
        "five-aggregates",
        "three-filters",
        "two-scalars",
        "two-windows",
        "lateral-top-one",
        "three-comma-joins",
        "two-aggregate-stages",
        "simple-write",
        "lateral-function",
    ],
)
def test_expansion_preserves_small_operational_queries(query: str) -> None:
    assert _check(f"import psycopg\ncursor.execute({query!r})\n", "evidence.py") == []


_NESTED_EVIDENCE_QUERY = """
WITH measurements AS (
    SELECT project.id, item.id AS item_id, stats.entries, stats.finished, stats.last_seen
    FROM project
    LEFT JOIN item ON item.project_id = project.id
    LEFT JOIN LATERAL (
        SELECT event.item_id,
               COUNT(delivery.id) AS entries,
               COUNT(delivery.id) FILTER (WHERE delivery.finished_at IS NOT NULL) AS finished,
               MAX(delivery.updated_at) AS last_seen
        FROM event
        LEFT JOIN delivery ON delivery.event_id = event.id
        WHERE event.item_id = item.id
        GROUP BY event.item_id
    ) stats ON TRUE
    WHERE project.id = %s
)
SELECT id, COUNT(DISTINCT item_id), SUM(entries), SUM(finished), MAX(last_seen)
FROM measurements
GROUP BY id
"""


_EXPANSION_CASES = (
    EvaluationCase(
        "nested-lateral-evidence",
        Language.PYTHON,
        f"import psycopg\ncursor.execute({_NESTED_EVIDENCE_QUERY!r})\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "evidence-is-not-executed",
        Language.PYTHON,
        f"import psycopg\nEXAMPLE = {_NESTED_EVIDENCE_QUERY!r}\n",
    ),
    EvaluationCase(
        "stored-evidence-lookup",
        Language.PYTHON,
        'import psycopg\ncursor.execute("SELECT completed, pending FROM job_progress WHERE id = %s")\n',
    ),
)


@pytest.mark.parametrize("case", _EXPANSION_CASES, ids=[case.case_id for case in _EXPANSION_CASES])
def test_evidence_query_regression(case: EvaluationCase) -> None:
    expected = 1 if case.expected is ExpectedOutcome.MATCH else 0
    assert len(_check(case.source, "dispatch_evidence.py")) == expected


@pytest.mark.parametrize(
    "query",
    [
        "INSERT INTO reservation VALUES (GREATEST((SELECT MAX(id) FROM a), (SELECT MAX(id) FROM b), (SELECT MAX(id) FROM c)) + 1)",
        "SELECT * FROM (SELECT COUNT(*) n FROM a) a CROSS JOIN (SELECT COUNT(*) n FROM b) b",
        "WITH a AS (SELECT COUNT(*) n FROM event), b AS (SELECT COUNT(*) n FROM other), c AS (SELECT COUNT(*) n FROM third) SELECT a.n FROM a JOIN b ON TRUE JOIN c ON TRUE",
    ],
)
def test_independent_aggregate_reads_do_not_form_an_aggregation_pipeline(query: str) -> None:
    assert _check(f"import psycopg\ncursor.execute({query!r})\n", "evidence.py") == []


@pytest.mark.parametrize("wrapper", ["({query})", "(({query}))", "LATERAL (({query}))"])
def test_parentheses_cannot_hide_a_complex_derived_relation(wrapper: str) -> None:
    relation = wrapper.format(
        query="SELECT event.id, COUNT(*) FROM event JOIN tag ON tag.event_id = event.id GROUP BY event.id"
    )
    source = f'import psycopg\ncursor.execute("SELECT * FROM owner JOIN {relation} totals ON TRUE")\n'  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert len(_check(source, "evidence.py")) == 1


def test_analytical_rule_keeps_precedence_for_reporting_queries() -> None:
    source = (
        "import psycopg\ncursor.execute(\"SELECT date_trunc('day', created_at), COUNT(*) FROM event GROUP BY 1\")\n"
    )
    path = Path("event_store.py")
    [diagnostic] = NoAnalyticalAggregationInPostgresStore().check(path, source)
    assert diagnostic.code == "SARJ020"
    assert _check(source, str(path)) == []


def test_write_root_does_not_hide_a_read_stage() -> None:
    query = """
        WITH a AS (SELECT id FROM event), b AS (SELECT id FROM a),
             c AS (SELECT id FROM b), d AS (SELECT id FROM c), e AS (SELECT id FROM d)
        UPDATE target SET active = TRUE WHERE id IN (SELECT id FROM e)
    """
    [diagnostic] = _check(f"import psycopg\ncursor.execute({query!r})\n", "evidence.py")
    assert "6 CTE/subquery stages" in diagnostic.message


@pytest.mark.parametrize(
    "query",
    [
        "SELECT COUNT(*) FILTER (WHERE status = 'queued'), COUNT(*) FILTER (WHERE status = 'running'), COUNT(*) FILTER (WHERE status = 'done'), COUNT(*) FILTER (WHERE status = 'failed') FROM job WHERE project_id = %s",
        "SELECT project.id, totals.n FROM project JOIN LATERAL (SELECT project_id, COUNT(*) n FROM job WHERE project_id = project.id GROUP BY project_id) totals ON TRUE WHERE project.id = %s",
        "SELECT * FROM (SELECT org_id, COUNT(*) FROM event GROUP BY org_id) totals",
        "SELECT * FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rank FROM event) ranked WHERE rank = 1",
        "SELECT * FROM (SELECT id FROM a UNION ALL SELECT id FROM b) combined",
        "SELECT * FROM (SELECT * FROM (SELECT id FROM event) inner_event) outer_event",
    ],
)
def test_simple_metrics_and_derived_lookups_do_not_require_review(query: str) -> None:
    assert _check(f"import psycopg\ncursor.execute({query!r})\n", "metrics.py") == []


@pytest.mark.parametrize(
    "query",
    [
        "SELECT COUNT(*), MIN(id), MAX(id), SUM(id), AVG(id), COUNT(DISTINCT id) FROM event",
        "SELECT COUNT(*) FILTER (WHERE a), COUNT(*) FILTER (WHERE b), COUNT(*) FILTER (WHERE c), COUNT(*) FILTER (WHERE d) FROM event",
        "SELECT (SELECT id FROM a), (SELECT id FROM b), (SELECT id FROM c) FROM event",
        "SELECT ROW_NUMBER() OVER (ORDER BY a), RANK() OVER (ORDER BY b), DENSE_RANK() OVER (ORDER BY c) FROM event",
        "WITH a AS (SELECT COUNT(*) n FROM event), b AS (SELECT MAX(n) n FROM a) SELECT SUM(n) FROM b",
    ],
)
def test_density_and_named_aggregate_stages_alone_are_allowed(query: str) -> None:
    assert _check(f"import psycopg\ncursor.execute({query!r})\n", "metrics.py") == []


@pytest.mark.parametrize(
    "branch",
    [
        "SELECT org_id FROM a GROUP BY org_id",
        "(SELECT org_id FROM a GROUP BY org_id)",
        "((SELECT org_id FROM a GROUP BY org_id))",
    ],
)
def test_parentheses_preserve_combined_set_operation_complexity(branch: str) -> None:
    query = "SELECT * FROM (" + branch + " UNION ALL SELECT org_id FROM b) totals"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    assert len(_check(f"import psycopg\ncursor.execute({query!r})\n", "metrics.py")) == 1


def test_native_cursor_follows_executed_module_constant_and_reports_original_sql() -> None:
    columns = ", ".join(f"version.field_{position}" for position in range(20))
    source = f"""from psycopg import AsyncCursor
QUERY = "SELECT {columns} FROM item version LEFT JOIN item base ON base.id=version.base_id WHERE version.id=%s"
async def read(cursor: AsyncCursor):
    await cursor.execute(QUERY, (1,))
"""  # ruff: ignore[hardcoded-sql-expression] -- parser fixture, never executed.
    [finding] = _check(source)
    assert finding.line == 2
    assert "Self-joined" in finding.message
    assert "20 projected expressions" in finding.message


def test_native_module_sql_binding_is_not_borrowed_after_shadowing() -> None:
    source = """from psycopg import AsyncCursor
QUERY = "SELECT id FROM item JOIN a ON TRUE JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE"
async def read(cursor: AsyncCursor, QUERY):
    await cursor.execute(QUERY)
"""
    assert _check(source) == []
    assert (
        _check(
            source.replace("cursor: AsyncCursor, QUERY", "cursor: AsyncCursor").replace(
                "    await", "    QUERY = 'SELECT id FROM item'\n    await"
            )
        )
        == []
    )


def test_native_constants_with_intervening_rebind_do_not_manufacture_coverage() -> None:
    source = """from psycopg import AsyncCursor
QUERY = "SELECT id FROM item JOIN a ON TRUE JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE"
QUERY = runtime_query()
async def read(cursor: AsyncCursor):
    await cursor.execute(QUERY)
"""
    assert _check(source) == []


def test_wide_self_join_threshold_preserves_ordinary_single_table_hydration() -> None:
    columns = ", ".join(f"a.field_{position}" for position in range(16))
    query = f"SELECT {columns} FROM item a JOIN item b ON b.id=a.parent_id"  # ruff: ignore[hardcoded-sql-expression] -- parser fixture, never executed.
    assert len(_check(f"import psycopg\ncursor.execute({query!r})")) == 1
    assert _check(f"import psycopg\ncursor.execute({query.replace(' JOIN item b ON b.id=a.parent_id', '')!r})") == []


def test_native_shared_query_is_reported_once_and_unused_constant_stays_silent() -> None:
    source = """from psycopg import AsyncCursor
QUERY = "SELECT id FROM item JOIN a ON TRUE JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE"
async def read(cursor: AsyncCursor):
    await cursor.execute(QUERY)
    await cursor.execute(QUERY)
"""
    assert len(_check(source)) == 1
    assert _check(source.split("async def", maxsplit=1)[0]) == []


@pytest.mark.parametrize(
    ("instance_mutation", "class_mutation", "expected_tables"),
    [
        ("", "", ("alpha", "beta")),
        ("", "AlphaStore._run = replacement", ("beta",)),
        ("", "del AlphaStore._run", ("beta",)),
        ("    def replace(self, replacement):\n        self._run = replacement\n", "", ("beta",)),
        ("    def replace(self):\n        del self._run\n", "", ("beta",)),
    ],
    ids=["unchanged", "class-replacement", "class-deletion", "instance-replacement", "instance-deletion"],
)
def test_same_named_query_wrappers_keep_mutations_scoped_to_their_owner(
    instance_mutation: str, class_mutation: str, expected_tables: tuple[str, ...]
) -> None:
    source = """from psycopg import AsyncCursor

class AlphaStore:
    async def _run(self, cursor: AsyncCursor, query: str):
        await cursor.execute(query)

    async def read(self, cursor: AsyncCursor):
        await self._run(
            cursor,
            "SELECT alpha.id FROM alpha "
            "JOIN a ON TRUE JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE",
        )

__INSTANCE_MUTATION__
class BetaStore:
    async def _run(self, cursor: AsyncCursor, query: str):
        await cursor.execute(query)

    async def read(self, cursor: AsyncCursor):
        await self._run(
            cursor,
            "SELECT beta.id FROM beta "
            "JOIN a ON TRUE JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE",
        )

__CLASS_MUTATION__
""".replace("__INSTANCE_MUTATION__", instance_mutation).replace("__CLASS_MUTATION__", class_mutation)
    findings = _check(source)
    expected_lines = [
        next(number for number, line in enumerate(source.splitlines(), start=1) if f"SELECT {table}.id" in line)
        for table in expected_tables
    ]
    assert [finding.line for finding in findings] == expected_lines
    assert all(finding.code == "SARJ437" and finding.severity is Severity.WARNING for finding in findings)


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("composable", [False, True])
def test_unknown_relation_holes_do_not_prove_a_wide_self_join(native: bool, composable: bool) -> None:
    columns = ", ".join(f"a.field_{position}" for position in range(16))
    query = f"SELECT {columns} FROM {{left}} a JOIN {{right}} b ON TRUE"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    expression = f"SQL({query!r}).format(left=left, right=right)" if composable else f"f{query!r}"
    prefix = "from psycopg.sql import SQL\n" if composable else "import psycopg\n"
    if native:
        source = prefix + f"from psycopg import Cursor\ndef read(handle: Cursor):\n    handle.execute({expression})\n"
    else:
        source = prefix + f"cursor.execute({expression})\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    ("relations", "expected"),
    [
        ("owner o JOIN item a ON TRUE JOIN item b ON TRUE", 1),
        ("owner o, item a, item b", 1),
        ('owner o JOIN public.item a ON TRUE JOIN public."item" b ON TRUE', 1),
        ('owner o JOIN item a ON TRUE JOIN "ITEM" b ON TRUE', 0),
        ("owner o JOIN alpha.item a ON TRUE JOIN beta.item b ON TRUE", 0),
        ("owner o JOIN item a ON TRUE JOIN other b ON TRUE", 0),
    ],
)
def test_wide_self_join_checks_every_explicit_relation_identity(relations: str, expected: int) -> None:
    columns = ", ".join(f"a.field_{position}" for position in range(16))
    query = f"SELECT {columns} FROM {relations}"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    findings = _check(f"import psycopg\ncursor.execute({query!r})\n")
    assert len(findings) == expected
    assert all("Self-joined" in finding.message for finding in findings)


def test_class_body_constructor_import_is_not_visible_inside_a_method() -> None:
    source = """import psycopg
class Store:
    from psycopg.sql import SQL
    def read(self, cursor):
        cursor.execute(SQL("SELECT id FROM item JOIN a ON TRUE JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE"))
"""
    assert _check(source) == []


def test_class_body_shadow_does_not_hide_a_method_global_constructor() -> None:
    source = """from psycopg.sql import SQL
class Store:
    SQL = staticmethod(lambda value: "SELECT 1")
    def read(self, cursor):
        cursor.execute(SQL("SELECT id FROM item JOIN a ON TRUE JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE"))
"""
    assert len(_check(source)) == 1


def test_class_body_can_use_its_own_constructor_import() -> None:
    source = """from psycopg import Cursor
class Store:
    from psycopg.sql import SQL
    cursor.execute(SQL("SELECT id FROM item JOIN a ON TRUE JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE"))
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize("lock", ["FOR UPDATE", "FOR NO KEY UPDATE", "FOR SHARE", "FOR KEY SHARE"])
def test_all_postgres_row_locks_preserve_atomic_statement_guidance(lock: str) -> None:
    query = f"SELECT id FROM item JOIN a ON TRUE JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE {lock}"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    [finding] = _check(f"import psycopg\ncursor.execute({query!r})\n")
    assert "preserve the atomic statement" in finding.message
    assert "review bounds, ordering, and locks" in finding.message


@pytest.mark.parametrize(
    "noise",
    ["'FOR UPDATE'", "$$FOR UPDATE$$", "1 /* FOR UPDATE */", "1 -- FOR UPDATE\n"],
)
def test_lock_text_in_sql_noise_does_not_change_review_guidance(noise: str) -> None:
    query = f"SELECT {noise} FROM item JOIN a ON TRUE JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE"  # ruff: ignore[hardcoded-sql-expression] -- synthetic lint-rule fixture
    [finding] = _check(f"import psycopg\ncursor.execute({query!r})\n")
    assert "preserve the atomic statement" not in finding.message
    assert "review cardinality" in finding.message


def test_deeply_nested_sql_abstains_without_crashing() -> None:
    query = "SELECT id FROM item JOIN a ON TRUE JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE"
    assert len(_check(f"import psycopg\ncursor.execute({query!r})\n")) == 1
    nested = "".join(("SELECT (" * 200, query, ") FROM item" * 200))
    assert _check(f"import psycopg\ncursor.execute({nested!r})\n") == []


def _executed_query_source(query: str, *, native: bool) -> str:
    if native:
        return f"from psycopg import Cursor\ndef read(handle: Cursor):\n    handle.execute({query!r})\n"
    return f"import psycopg\ncursor.execute({query!r})\n"


@pytest.mark.parametrize("backend", ["sqlite3", "aiosqlite"])
@pytest.mark.parametrize("form", ["literal", "module-binding", "same-class-wrapper"])
def test_mixed_sqlite_import_keeps_import_proven_psycopg_execution(backend: str, form: str) -> None:
    query = "SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE"
    prefix = f"import {backend}\nfrom psycopg import Cursor\n"
    match form:
        case "literal":
            source = prefix + f"def read(handle: Cursor):\n    handle.execute({query!r})\n"
        case "module-binding":
            source = prefix + f"QUERY = {query!r}\ndef read(handle: Cursor):\n    handle.execute(QUERY)\n"
        case _:
            source = prefix + (
                "class Store:\n"
                "    def _run(self, handle: Cursor, statement):\n"
                "        handle.execute(statement)\n"
                "    def read(self, handle: Cursor):\n"
                f"        self._run(handle, {query!r})\n"
            )
    assert len(_check(source, "mixed_adapter.py")) == 1
    assert _check(f"import {backend}\n" + _executed_query_source(query, native=False), "mixed_adapter.py") == []


def test_mixed_typed_backends_keep_psycopg_and_sqlite_execution_distinct() -> None:
    query = "SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE"
    source = (
        "from psycopg import Cursor as PgCursor\n"
        "from sqlite3 import Cursor as LiteCursor\n"
        "def read(primary: PgCursor, secondary: LiteCursor):\n"
        f"    primary.execute({query!r})\n"
        f"    secondary.execute({query!r})\n"
    )
    [finding] = _check(source)
    assert finding.line == 4


@pytest.mark.parametrize("projection", ["a._peerdb_version", "a.argMax", "uniqExact(a.id)", "COUNTIF(a.active)"])
def test_native_postgres_ownership_precedes_overlapping_dialect_identifiers(projection: str) -> None:
    query = f"SELECT {projection} FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE"  # ruff: ignore[hardcoded-sql-expression] -- synthetic parser fixture, never executed.
    assert len(_check(_executed_query_source(query, native=True))) == 1
    assert _check(_executed_query_source(query, native=False)) == []


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize(
    ("relations", "expected"),
    [
        ("(a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE)", 1),
        ("(a JOIN b ON TRUE JOIN c ON TRUE) JOIN (d JOIN e ON TRUE) ON TRUE", 1),
        ("(a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE)", 0),
        (
            (
                "a JOIN b ON TRUE JOIN c ON TRUE JOIN "
                "(SELECT d.id FROM d JOIN e ON TRUE JOIN f ON TRUE JOIN g ON TRUE) q ON TRUE"
            ),
            0,
        ),
    ],
)
def test_parenthesized_joins_retain_their_select_owner(native: bool, relations: str, expected: int) -> None:
    query = f"SELECT a.id FROM {relations}"  # ruff: ignore[hardcoded-sql-expression] -- synthetic parser fixture, never executed.
    assert len(_check(_executed_query_source(query, native=native))) == expected


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize(
    ("width", "relations", "expected"),
    [
        (16, "(item a JOIN item b ON TRUE)", 1),
        (16, "owner o JOIN (item a JOIN item b ON TRUE) ON TRUE", 1),
        (15, "(item a JOIN item b ON TRUE)", 0),
        (16, "(alpha.item a JOIN beta.item b ON TRUE)", 0),
        (25, "(item a JOIN other b ON TRUE JOIN third c ON TRUE)", 1),
        (24, "(item a JOIN other b ON TRUE JOIN third c ON TRUE)", 0),
    ],
)
def test_grouped_relations_preserve_projection_thresholds(
    native: bool, width: int, relations: str, expected: int
) -> None:
    columns = ", ".join(f"a.field_{position}" for position in range(width))
    query = f"SELECT {columns} FROM {relations}"  # ruff: ignore[hardcoded-sql-expression] -- synthetic parser fixture, never executed.
    assert len(_check(_executed_query_source(query, native=native))) == expected


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            (
                "SELECT * FROM (owner o JOIN "
                "(SELECT item.id, COUNT(*) FROM item JOIN tag ON TRUE GROUP BY item.id) totals ON TRUE)"
            ),
            1,
        ),
        ("SELECT * FROM (SELECT item.id, COUNT(*) FROM (item JOIN tag ON TRUE) GROUP BY item.id) totals", 1),
        (
            (
                "SELECT * FROM (SELECT * FROM (owner o JOIN "
                "(SELECT id, ROW_NUMBER() OVER (ORDER BY id) rank FROM item) ranked ON TRUE)) envelope"
            ),
            1,
        ),
        ("SELECT * FROM (owner o JOIN (SELECT id FROM item WHERE id=%s) bounded ON TRUE)", 0),
        (
            (
                "SELECT * FROM (SELECT id FROM item WHERE EXISTS "
                "(SELECT ROW_NUMBER() OVER (ORDER BY id) FROM tag)) results"
            ),
            0,
        ),
    ],
)
def test_grouped_derived_relations_keep_transform_ownership(native: bool, query: str, expected: int) -> None:
    assert len(_check(_executed_query_source(query, native=native))) == expected


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("parenthesized", [False, True])
@pytest.mark.parametrize("stages", [5, 6])
def test_statement_parentheses_do_not_add_a_read_stage(native: bool, parenthesized: bool, stages: int) -> None:
    stage_sql = [f"s{position} AS (SELECT id FROM item)" for position in range(stages)]  # ruff: ignore[hardcoded-sql-expression] -- fixed stage-count parser fixtures, never executed.
    query = "WITH " + ", ".join(stage_sql) + " SELECT id FROM s0"  # ruff: ignore[hardcoded-sql-expression] -- fixed stage-count parser fixtures, never executed.
    if parenthesized:
        query = f"({query})"
    assert len(_check(_executed_query_source(query, native=native))) == (1 if stages >= 6 else 0)


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize(
    "query",
    [
        "SELECT id FROM a UNION ALL SELECT id FROM b UNION ALL SELECT id FROM c UNION ALL SELECT id FROM d",
        (
            "SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE "
            "UNION ALL SELECT id FROM e UNION ALL SELECT id FROM f"
        ),
    ],
)
def test_set_operators_do_not_double_count_select_stages(native: bool, query: str) -> None:
    assert _check(_executed_query_source(query, native=native)) == []


def test_deep_grouped_store_query_abstains_before_legacy_overlap_can_overflow() -> None:
    query = "SELECT COUNT(*) FROM (" * 200 + "SELECT id FROM item" + ") grouped GROUP BY id" * 200
    assert _check(_executed_query_source(query, native=False), "item_store.py") == []


def test_legacy_store_overlap_does_not_log_unsupported_sql(caplog: pytest.LogCaptureFixture) -> None:
    query = "SELECT COUNT(*) FROM item GROUP BY id; VACUUM private_synthetic_marker"
    assert _check(_executed_query_source(query, native=False), "item_store.py") == []
    assert caplog.records == []


@pytest.mark.parametrize("native", [False, True])
def test_deep_python_query_composition_abstains_without_crashing(native: bool) -> None:
    query = "SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE"
    expression = repr(query) + ' + ""' * 1200
    source = (
        f"from psycopg import Cursor\ndef read(handle: Cursor):\n    handle.execute({expression})\n"
        if native
        else f"import psycopg\ncursor.execute({expression})\n"
    )
    assert _check(source) == []


@pytest.mark.parametrize("delegates", [False, True])
def test_local_class_construction_does_not_prove_database_execution(delegates: bool) -> None:
    method = "self.handle.execute(query)" if delegates else "len(query)"
    source = """import psycopg
class Renderer:
    def execute(self, query):
        return __METHOD__
cursor = Renderer()
cursor.execute("SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE")
""".replace("__METHOD__", method)
    assert _check(source) == []


def test_native_same_class_forwarding_survives_conventional_class_abstention() -> None:
    source = """from psycopg import Cursor
class Store:
    def __init__(self, handle: Cursor):
        self.handle = handle
    def _run(self, query):
        self.handle.execute(query)
    def read(self):
        self._run("SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE")
"""
    assert len(_check(source)) == 1


def test_unproven_factory_does_not_create_a_local_class_exclusion() -> None:
    source = """import psycopg
def make_cursor():
    return runtime_cursor()
class Unrelated:
    pass
cursor = make_cursor()
cursor.execute("SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE")
"""
    assert len(_check(source)) == 1


def test_deep_composition_with_a_local_class_still_abstains_safely() -> None:
    query = "SELECT a.id FROM a JOIN b ON TRUE JOIN c ON TRUE JOIN d ON TRUE JOIN e ON TRUE"
    expression = repr(query) + ' + ""' * 1200
    source = f"import psycopg\nclass Unrelated:\n    pass\ncursor.execute({expression})\n"
    assert _check(source) == []
