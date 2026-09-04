from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_psycopg_execution_outside_injected_owner import (
    NoPsycopgExecutionOutsideInjectedOwner,
)


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "app/store.py"):
    return NoPsycopgExecutionOutsideInjectedOwner().check(Path(path), source)


@pytest.mark.parametrize(
    "source",
    [
        """
from psycopg import Connection

def mark(conn: Connection):
    conn.execute("UPDATE calls SET retry = true")
""",
        """
from psycopg_pool import AsyncConnectionPool

async def mark(pool: AsyncConnectionPool):
    async with pool.connection() as conn, conn.cursor() as cursor:
        await cursor.executemany("INSERT INTO calls VALUES (%s)", [(1,)])
""",
        """
import psycopg as pg

def mark(conn: pg.Connection):
    alias = conn
    alias.execute("DELETE FROM calls")
""",
        """
from typing import Annotated
from psycopg import Connection as DbConnection

def mark(conn: Annotated[DbConnection | None, "database"]):
    if conn is not None:
        conn.execute("UPDATE calls SET retry = true")
""",
        """
import psycopg

def mark(dsn: str):
    conn = psycopg.connect(dsn)
    cursor = conn.cursor()
    cursor.execute("UPDATE calls SET retry = true")
""",
        """
from psycopg_pool import ConnectionPool

def mark(dsn: str):
    pool = ConnectionPool(dsn)
    with pool.connection() as conn:
        conn.execute("UPDATE calls SET retry = true")
""",
    ],
)
def test_reports_import_proven_external_psycopg_execution(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ415"
    assert findings[0].severity.value == "warning"


@pytest.mark.parametrize(
    "source",
    [
        """
from psycopg_pool import AsyncConnectionPool

class Store:
    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    async def mark(self):
        async with self.pool.connection() as conn, conn.cursor() as cursor:
            await cursor.execute("UPDATE calls SET retry = true")
""",
        """
from psycopg import Connection

class Store:
    def __init__(self, connection: Connection, /):
        self.connection: Connection = connection

    def mark(self):
        self.connection.execute("UPDATE calls SET retry = true")
""",
    ],
)
def test_allows_execution_owned_by_constructor_injection(source: str) -> None:
    assert _check(source) == []


def test_does_not_trust_unimported_or_unrelated_database_lookalikes() -> None:
    local = """
class Connection: ...

def run(conn: Connection):
    conn.execute(job)
"""
    unrelated = """
from vendor.client import ConnectionPool

def run(pool: ConnectionPool):
    with pool.connection() as conn:
        conn.execute(job)
"""
    assert _check(local) == []
    assert _check(unrelated) == []


def test_rebinding_clears_psycopg_origin() -> None:
    source = """
from psycopg import Connection

def run(conn: Connection, executor):
    conn = executor
    conn.execute(job)
"""
    assert _check(source) == []


def test_later_binding_does_not_hide_earlier_external_execution() -> None:
    source = """
from psycopg import Connection

def run(conn: Connection, executor):
    conn.execute("SELECT id FROM calls")
    conn = executor
"""
    assert len(_check(source)) == 1


def test_control_flow_keeps_only_origins_shared_by_every_exit() -> None:
    source = """
from psycopg import Connection

def run(conn: Connection, executor, enabled: bool):
    if enabled:
        current = conn
    else:
        current = executor
    current.execute(job)
"""
    assert _check(source) == []


def test_nested_scope_is_analyzed_once_without_inheriting_parent_bindings() -> None:
    source = """
from psycopg import Connection

def outer(conn: Connection):
    if enabled:
        def inner(other: Connection):
            other.execute("SELECT id FROM calls")
"""
    findings = _check(source)
    assert len(findings) == 1


def test_constructor_proof_is_direct_and_source_ordered() -> None:
    conditional = """
from psycopg_pool import ConnectionPool

class Store:
    def __init__(self, pool: ConnectionPool, enabled: bool):
        if enabled:
            self.pool = pool

    def run(self):
        self.pool.execute("SELECT id FROM calls")
"""
    rebound = """
from psycopg_pool import ConnectionPool

class Store:
    def __init__(self, pool: ConnectionPool, fallback):
        pool = fallback
        self.pool = pool

    def run(self):
        self.pool.execute("SELECT id FROM calls")
"""
    duplicate = """
from psycopg_pool import ConnectionPool

class Store:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool
    def __init__(self, pool: ConnectionPool):
        self.pool = pool
    def run(self):
        self.pool.execute("SELECT id FROM calls")
"""
    assert _check(conditional) == []
    assert _check(rebound) == []
    assert _check(duplicate) == []


def test_later_attribute_mutation_revokes_constructor_ownership_proof() -> None:
    source = """
from psycopg_pool import ConnectionPool

class Store:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def replace(self, value):
        self.pool = value

    def run(self):
        self.pool.execute("SELECT id FROM calls")
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_store.py",
        "test_support/database.py",
        "migrations/001_backfill.py",
        "scripts/backfill.py",
        "tools/seed.py",
    ],
)
def test_excludes_intentional_test_and_operational_owners(path: str) -> None:
    source = """
from psycopg import Connection

def run(conn: Connection):
    conn.execute("UPDATE calls SET retry = true")
"""
    assert _check(source, path) == []


def test_excludes_literal_connection_probe_without_exempting_generic_checks() -> None:
    probe = """
from psycopg import Connection

def start(conn: Connection):
    conn.execute("SELECT 1;")
"""
    write = probe.replace("start", "check").replace("SELECT 1;", "DELETE FROM calls")
    assert _check(probe) == []
    assert len(_check(write)) == 1


def test_exact_suppression_applies_only_to_sarj415() -> None:
    suppressed = """
from psycopg import Connection

def run(conn: Connection):
    conn.execute("SELECT id FROM calls")  # sarj-noqa: SARJ415 - driver contract probe
"""
    unrelated = suppressed.replace("SARJ415", "SARJ999")
    assert _check(suppressed) == []
    assert len(_check(unrelated)) == 1


def test_ignores_generated_and_malformed_source() -> None:
    generated = """
# Generated by sqlacodegen
from psycopg import Connection
def run(conn: Connection):
    conn.execute("SELECT id FROM calls")
"""
    assert _check(generated) == []
    assert _check("def incomplete(") == []


def test_only_unwraps_supported_annotation_wrappers() -> None:
    generic_connection = """
from psycopg import Connection

def run(conn: Connection[tuple]):
    conn.execute("SELECT id FROM calls")
"""
    containing_wrapper = """
from psycopg import Connection

class Batch: ...

def run(batch: Batch[Connection]):
    batch.execute(job)
"""
    mixed_union = """
from psycopg import Connection
from vendor import Executor

def run(value: Connection | Executor):
    value.execute(job)
"""
    assert len(_check(generic_connection)) == 1
    assert _check(containing_wrapper) == []
    assert _check(mixed_union) == []


def test_ambiguous_aliases_and_shadowed_imports_abstain() -> None:
    ambiguous_alias = """
from psycopg import Connection

Db = str
def run(value: Db):
    value.execute(job)
Db = Connection
"""
    shadowed_parameter = """
from psycopg import Connection

def run(Connection):
    conn = Connection()
    conn.execute(job)
"""
    shadowed_class = """
from psycopg import Connection

class Connection: ...
def run():
    conn = Connection()
    conn.execute(job)
"""
    assert _check(ambiguous_alias) == []
    assert _check(shadowed_parameter) == []
    assert _check(shadowed_class) == []


def test_tracks_global_and_constructor_local_psycopg_owners() -> None:
    global_pool = """
from psycopg_pool import ConnectionPool

pool = ConnectionPool("postgresql://db")
def run():
    with pool.connection() as conn:
        conn.execute("SELECT id FROM calls")
"""
    constructor_alias = """
from psycopg_pool import ConnectionPool

class Store:
    def __init__(self):
        pool = ConnectionPool("postgresql://db")
        self.pool = pool

    def run(self):
        with self.pool.connection() as conn:
            conn.execute("SELECT id FROM calls")
"""
    assert len(_check(global_pool)) == 1
    assert len(_check(constructor_alias)) == 1


def test_reflective_attribute_mutation_revokes_owner_proof() -> None:
    source = """
from psycopg_pool import ConnectionPool

class Store:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def replace(self, value):
        setattr(self, "pool", value)

    def run(self):
        self.pool.execute("SELECT id FROM calls")
"""
    assert _check(source) == []
    dynamic = source.replace('setattr(self, "pool", value)', "setattr(self, name, value)")
    assert _check(dynamic) == []


def test_non_fallthrough_branches_do_not_pollute_reachable_state() -> None:
    source = """
from psycopg import Connection

def run(conn: Connection, other, stop: bool):
    if stop:
        conn = other
        return
    conn.execute("SELECT id FROM calls")
"""
    dead = source.replace(
        '    conn.execute("SELECT id FROM calls")', '    return\n    conn.execute("SELECT id FROM calls")'
    )
    assert len(_check(source)) == 1
    assert _check(dead) == []


def test_operational_exclusion_does_not_hide_nested_application_modules() -> None:
    source = """
from psycopg import Connection

def run(conn: Connection):
    conn.execute("SELECT id FROM calls")
"""
    assert _check(source, "scripts/backfill.py") == []
    assert _check(source, "python/scripts/backfill.py") == []
    assert len(_check(source, "app/tools/store.py")) == 1
    assert len(_check(source, "app/admin/users.py")) == 1


def test_health_exclusion_does_not_hide_unrelated_writes() -> None:
    source = """
from psycopg import Connection

def ping_customer(conn: Connection):
    conn.execute("DELETE FROM customers")

def health_record_update(conn: Connection):
    conn.execute("UPDATE health_records SET checked = true")
"""
    assert len(_check(source)) == 2


def test_all_binding_forms_shadow_imported_database_constructors() -> None:
    sources = [
        """
from psycopg import Connection
def run():
    from vendor import Connection
    conn = Connection()
    conn.execute(job)
""",
        """
from psycopg import Connection
def run(factories):
    for Connection in factories:
        conn = Connection()
        conn.execute(job)
""",
        """
from psycopg import Connection
def run(factory):
    with factory as Connection:
        conn = Connection()
        conn.execute(job)
""",
        """
from psycopg import Connection
def run(factories):
    return [Connection().execute(job) for Connection in factories]
""",
        """
from psycopg import Connection
def run(factory):
    if (Connection := factory):
        Connection().execute(job)
""",
        """
from psycopg import Connection
def run():
    try:
        work()
    except Error as Connection:
        Connection().execute(job)
""",
        """
from psycopg import Connection
def run(value):
    match value:
        case Connection:
            Connection().execute(job)
""",
    ]
    assert all(_check(source) == [] for source in sources)


def test_tracks_annotated_external_creators() -> None:
    module_global = """
from psycopg_pool import ConnectionPool
pool: ConnectionPool = ConnectionPool("postgresql://db")
def run():
    pool.execute("UPDATE calls SET retry = true")
"""
    constructor_local = """
from psycopg_pool import ConnectionPool
class Store:
    def __init__(self):
        pool: ConnectionPool = ConnectionPool("postgresql://db")
        self.pool = pool
    def run(self):
        self.pool.execute("UPDATE calls SET retry = true")
"""
    assert len(_check(module_global)) == 1
    assert len(_check(constructor_local)) == 1


def test_walrus_assignments_preserve_psycopg_origin() -> None:
    sources = [
        """
import psycopg
def run(dsn: str):
    if conn := psycopg.connect(dsn):
        conn.execute("DELETE FROM calls")
""",
        """
from psycopg import Connection
def run(conn: Connection):
    if current := conn:
        current.execute("DELETE FROM calls")
""",
        """
import psycopg
def run(dsn: str):
    (conn := psycopg.connect(dsn)).execute("DELETE FROM calls")
""",
    ]
    assert [len(_check(source)) for source in sources] == [1, 1, 1]


@pytest.mark.parametrize("example", NoPsycopgExecutionOutsideInjectedOwner.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count
