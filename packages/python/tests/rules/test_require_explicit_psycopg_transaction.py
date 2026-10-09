from pathlib import Path
from textwrap import indent

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language
from sarj_rule_contracts.examples import verify_native_rule

from sarj_python_lint.__main__ import analyze
from sarj_python_lint.rules.require_explicit_psycopg_transaction import RequireExplicitPsycopgTransaction


def _source(body: str, *, transaction: str = "", annotation: str = "AsyncConnectionPool") -> str:
    return (
        "from psycopg_pool import AsyncConnectionPool\n"
        f"async def save(pool: {annotation}):\n"
        f"    async with pool.connection() as conn{transaction}, conn.cursor() as cur:\n"
        + indent(body, "        ")
        + "\n"
    )


_WRITES = 'await cur.execute("INSERT INTO items VALUES (1)")\nawait cur.execute("UPDATE totals SET n = n + 1")'
_LOCK = 'await cur.execute("SELECT id FROM items FOR UPDATE")\nawait cur.execute("UPDATE items SET n = 1")'
CASES = (
    EvaluationCase("two-writes", Language.PYTHON, _source(_WRITES), ExpectedOutcome.MATCH),
    EvaluationCase("locking-read", Language.PYTHON, _source(_LOCK), ExpectedOutcome.MATCH),
    EvaluationCase("explicit-transaction", Language.PYTHON, _source(_WRITES, transaction=", conn.transaction()")),
    EvaluationCase("protected-lock", Language.PYTHON, _source(_LOCK, transaction=", conn.transaction()")),
    EvaluationCase("single-write", Language.PYTHON, _source('await cur.execute("UPDATE items SET n = 1")')),
    EvaluationCase(
        "read-then-write",
        Language.PYTHON,
        _source('await cur.execute("SELECT id FROM items")\nawait cur.execute("UPDATE items SET n = 1")'),
    ),
    EvaluationCase(
        "exclusive-branches",
        Language.PYTHON,
        _source(
            'if replace:\n    await cur.execute("UPDATE items SET n = 1")\nelse:\n    await cur.execute("INSERT INTO items VALUES (1)")'
        ),
    ),
    EvaluationCase(
        "terminated-branch",
        Language.PYTHON,
        _source(
            'if replace:\n    await cur.execute("UPDATE items SET n = 1")\n    return\nawait cur.execute("INSERT INTO items VALUES (1)")'
        ),
    ),
    EvaluationCase(
        "branch-followed-by-write",
        Language.PYTHON,
        _source(
            'if replace:\n    await cur.execute("UPDATE items SET n = 1")\nawait cur.execute("INSERT INTO items VALUES (1)")'
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "atomic-cte",
        Language.PYTHON,
        _source(
            'await cur.execute("WITH picked AS (SELECT id FROM items FOR UPDATE) UPDATE items SET n = 1 FROM picked WHERE items.id = picked.id")'
        ),
    ),
    EvaluationCase("sql-comment", Language.PYTHON, _source('await cur.execute("SELECT 1 -- FOR UPDATE")')),
    EvaluationCase("sql-string", Language.PYTHON, _source("await cur.execute(\"SELECT 'FOR UPDATE'\")")),
    EvaluationCase(
        "executemany-and-write",
        Language.PYTHON,
        _source(
            _WRITES.replace(
                'cur.execute("INSERT INTO items VALUES (1)")', 'cur.executemany("INSERT INTO items VALUES (%s)", rows)'
            )
        ),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("unproven-pool", Language.PYTHON, _source(_WRITES, annotation="OtherPool")),
    EvaluationCase(
        "connection-alias",
        Language.PYTHON,
        _source("alias = conn\nasync with alias.transaction():\n" + indent(_WRITES, "    ")),
    ),
    EvaluationCase(
        "cursor-alias",
        Language.PYTHON,
        _source("alias = cur\n" + _WRITES.replace("cur.", "alias.")),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "wrong-transaction",
        Language.PYTHON,
        _source(_WRITES, transaction=", unrelated.transaction()"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "expired-transaction",
        Language.PYTHON,
        _source("async with conn.transaction():\n    pass\n" + _WRITES),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("nested-function", Language.PYTHON, _source("async def deferred():\n" + indent(_WRITES, "    "))),
    EvaluationCase("rebound-cursor", Language.PYTHON, _source("cur = unrelated\n" + _WRITES)),
    EvaluationCase("malformed-python", Language.PYTHON, "async def save(:"),
)


@pytest.mark.parametrize("case", CASES, ids=tuple(case.case_id for case in CASES))
def test_labeled_cases(case: EvaluationCase) -> None:
    diagnostics = RequireExplicitPsycopgTransaction().check(Path("repository.py"), case.source)
    assert len(diagnostics) == (1 if case.expected is ExpectedOutcome.MATCH else 0)


def test_documented_examples() -> None:
    verify_native_rule(RequireExplicitPsycopgTransaction, analyze)


@pytest.mark.parametrize("path", ["tests/test_repository.py", "conftest.py", "generated/repository_pb2.py"])
def test_excluded_files(path: str) -> None:
    assert not RequireExplicitPsycopgTransaction().check(Path(path), _source(_WRITES))


def test_suppression_is_exact_and_diagnostics_are_stable() -> None:
    source = _source(_LOCK.replace("\n", "  # sarj-noqa: SARJ462\n", 1))
    rule = RequireExplicitPsycopgTransaction()
    assert not rule.check(Path("repository.py"), source)
    source = source.replace("SARJ462", "SARJ415")
    assert len(rule.check(Path("repository.py"), source)) == 1
    assert rule.check(Path("repository.py"), source) == rule.check(Path("repository.py"), source)


def test_injected_class_pool_and_module_sql_constant() -> None:
    source = """from psycopg_pool import AsyncConnectionPool as Pool
from psycopg.sql import SQL
QUERY = SQL("SELECT id FROM items FOR UPDATE")
class Repository:
    def __init__(self, pool: Pool):
        self.pool = pool
    async def save(self):
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(QUERY)
            await cur.execute("UPDATE items SET n = 1")
"""
    assert len(RequireExplicitPsycopgTransaction().check(Path("repository.py"), source)) == 1


def test_separate_connections_do_not_share_write_history() -> None:
    source = _source('await cur.execute("UPDATE items SET n = 1")')
    source += '    async with pool.connection() as conn:\n        await conn.execute("UPDATE totals SET n = 1")\n'
    assert not RequireExplicitPsycopgTransaction().check(Path("repository.py"), source)


@pytest.mark.parametrize(
    "body",
    [
        'await cur.execute("SELECT id FROM items FOR UPDATE")',
        'callback = lambda: cur.execute("UPDATE items SET n = 1")\nawait cur.execute("UPDATE totals SET n = 1")',
        'await cur.execute("INSERT INTO items VALUES (1); UPDATE totals SET n = 1")',
        'await cur.execute("SELECT id FROM items FOR UPDATE")\nreturn\nawait cur.execute("UPDATE items SET n = 1")',
        'if False:\n    await cur.execute("UPDATE items SET n = 1")\nawait cur.execute("UPDATE totals SET n = 1")',
    ],
)
def test_no_multi_statement_atomicity_requirement(body: str) -> None:
    assert not RequireExplicitPsycopgTransaction().check(Path("repository.py"), _source(body))


def test_three_writes_have_one_actionable_diagnostic() -> None:
    source = _source(
        'await cur.execute("INSERT INTO items VALUES (1)")\nawait cur.execute("UPDATE totals SET n = 1")\nawait cur.execute("DELETE FROM old_items")'
    )
    assert len(RequireExplicitPsycopgTransaction().check(Path("repository.py"), source)) == 1


def test_sync_connection_parameter_and_import_alias() -> None:
    source = """import psycopg as pg
def save(conn: pg.Connection):
    conn.execute("INSERT INTO items VALUES (1)")
    conn.execute("DELETE FROM old_items")
"""
    assert len(RequireExplicitPsycopgTransaction().check(Path("repository.py"), source)) == 1


def test_generated_header_excludes_finding() -> None:
    assert not RequireExplicitPsycopgTransaction().check(Path("repository.py"), "# @generated\n" + _source(_WRITES))


def test_parameter_shadows_module_sql_constant() -> None:
    source = """from psycopg_pool import AsyncConnectionPool
QUERY = "UPDATE items SET n = 1"
async def save(pool: AsyncConnectionPool, QUERY: str):
    async with pool.connection() as conn:
        await conn.execute(QUERY)
        await conn.execute("UPDATE totals SET n = 1")
"""
    assert not RequireExplicitPsycopgTransaction().check(Path("repository.py"), source)


def test_injected_owner_and_transaction_rules_have_distinct_responsibilities(tmp_path: Path) -> None:
    path = tmp_path / "repository.py"
    path.write_text("""from psycopg_pool import AsyncConnectionPool
class Repository:
    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool
    async def save(self):
        async with self.pool.connection() as conn:
            await conn.execute("INSERT INTO items VALUES (1)")
            await conn.execute("UPDATE totals SET n = 1")
""")
    diagnostics = analyze(
        ["no-psycopg-execution-outside-injected-owner", "require-explicit-psycopg-transaction"], [path]
    )
    assert [item.code for item in diagnostics] == ["SARJ462"]
