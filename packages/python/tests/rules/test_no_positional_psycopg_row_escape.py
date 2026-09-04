from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rules.no_positional_psycopg_row_escape import NoPositionalPsycopgRowEscape


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


def _check(source: str, path: str = "app/task_store.py"):
    return NoPositionalPsycopgRowEscape().check(Path(path), source)


@pytest.mark.parametrize(
    "source",
    [
        """
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cursor:
            return cursor.fetchone()
""",
        """
import psycopg as pg

async def load(dsn: str):
    async with await pg.AsyncConnection.connect(dsn) as conn:
        async with conn.cursor() as cursor:
            rows = await cursor.fetchall()
            return rows
""",
        """
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]]):
    with conn.cursor() as cursor:
        return cursor.fetchmany()
""",
        """
from psycopg import Connection
from psycopg.rows import tuple_row

def load(conn: Connection[object]):
    with conn.cursor(row_factory=tuple_row) as cursor:
        return cursor.execute("SELECT id, state FROM task").fetchone()
""",
        """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from psycopg_pool import AsyncConnectionPool

class Store:
    def __init__(self, pool: AsyncConnectionPool[AsyncConnection[tuple[object, ...]]]) -> None:
        self.pool = pool

    async def load(self):
        async with self.pool.connection() as conn, conn.cursor() as cursor:
            return await cursor.fetchone()
""",
    ],
)
def test_flags_proven_positional_record_escape(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ414"
    assert findings[0].severity.value == "warning"


@pytest.mark.parametrize(
    ("imports", "annotation"),
    [
        ("from psycopg.rows import TupleRow", "TupleRow"),
        ("import psycopg.rows as rows", "rows.TupleRow"),
    ],
)
def test_flags_import_proven_psycopg_tuple_row_annotation(imports: str, annotation: str) -> None:
    source = f"""
from psycopg import Connection
{imports}

def load(conn: Connection[{annotation}]):
    with conn.cursor() as cursor:
        return cursor.fetchone()
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "factory",
    ["class_row(TaskRow)", "dict_row", "kwargs_row(TaskRow.model_validate)", "namedtuple_row", "scalar_row"],
)
def test_allows_import_proven_named_or_scalar_factories(factory: str) -> None:
    source = f"""
from psycopg import Connection
from psycopg.rows import class_row, dict_row, kwargs_row, namedtuple_row, scalar_row

def load(conn: Connection[tuple[object, ...]]):
    with conn.cursor(row_factory={factory}) as cursor:
        return cursor.fetchone()
"""
    assert _check(source) == []


def test_allows_connection_level_factory() -> None:
    source = """
import psycopg
from psycopg.rows import class_row

def load(dsn: str):
    with psycopg.connect(dsn, row_factory=class_row(TaskRow)) as conn:
        with conn.cursor() as cursor:
            return cursor.fetchone()
"""
    assert _check(source) == []


def test_abstains_after_connection_factory_assignment() -> None:
    source = """
import psycopg
from psycopg.rows import class_row

def load(dsn: str):
    with psycopg.connect(dsn) as conn:
        conn.row_factory = class_row(TaskRow)
        with conn.cursor() as cursor:
            return cursor.fetchone()
"""
    assert _check(source) == []


def test_cursor_factory_assignment_is_order_aware() -> None:
    safe = """
import psycopg
from psycopg.rows import class_row

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        cursor.row_factory = class_row(TaskRow)
        return cursor.fetchone()
"""
    unsafe = """
import psycopg
from psycopg.rows import class_row, tuple_row

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor(row_factory=class_row(TaskRow)) as cursor:
        cursor.row_factory = tuple_row
        return cursor.fetchone()
"""
    assert _check(safe) == []
    assert len(_check(unsafe)) == 1


def test_setattr_row_factory_mutations_abstain() -> None:
    cursor = """
import psycopg
from psycopg.rows import dict_row

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        setattr(cursor, "row_factory", dict_row)
        return cursor.fetchone()
"""
    connection = """
import psycopg
from psycopg.rows import dict_row

def load(dsn: str):
    with psycopg.connect(dsn) as conn:
        setattr(conn, "row_factory", dict_row)
        with conn.cursor() as cursor:
            return cursor.fetchone()
"""
    assert _check(cursor) == []
    assert _check(connection) == []


@pytest.mark.parametrize(
    "source",
    [
        """
def load(conn):
    with conn.cursor() as cursor:
        return cursor.fetchone()
""",
        """
import sqlite3

def load(conn: sqlite3.Connection):
    with conn.cursor() as cursor:
        return cursor.fetchone()
""",
        """
from psycopg import Connection

def load(conn: Connection):
    with conn.cursor() as cursor:
        return cursor.fetchone()
""",
        """
from psycopg import Connection
from psycopg.rows import class_row

def class_row(model):
    return model

def load(conn: Connection[tuple[object, ...]]):
    with conn.cursor(row_factory=class_row(TaskRow)) as cursor:
        return cursor.fetchone()
""",
        """
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]], row_factory):
    with conn.cursor(row_factory=row_factory) as cursor:
        return cursor.fetchone()
""",
    ],
)
def test_abstains_without_proven_positional_psycopg_factory(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "returned",
    [
        "bool(cursor.fetchone())",
        "cursor.fetchone()[0]",
        "Task.model_validate(cursor.fetchone())",
        "[Task(*row) for row in cursor.fetchall()]",
    ],
)
def test_allows_locally_transformed_results(returned: str) -> None:
    source = f"""
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        return {returned}
"""
    assert _check(source) == []


def test_correlates_fetch_with_exact_cursor_lifetime() -> None:
    source = """
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE task SET ready = true")
        with conn.cursor(row_factory=unknown_factory) as cursor:
            return cursor.fetchone()
"""
    assert _check(source) == []


def test_cursor_rebinding_before_fetch_abstains() -> None:
    source = """
import psycopg

def load(dsn: str, other):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        cursor = other
        return cursor.fetchone()
"""
    assert _check(source) == []


def test_connection_and_pool_rebinding_abstain() -> None:
    connection = """
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]], other):
    conn = other
    with conn.cursor() as cursor:
        return cursor.fetchone()
"""
    pool = """
from psycopg import Connection
from psycopg_pool import ConnectionPool

def load(pool: ConnectionPool[Connection[tuple[object, ...]]], other):
    pool = other
    with pool.connection() as conn, conn.cursor() as cursor:
        return cursor.fetchone()
"""
    assert _check(connection) == []
    assert _check(pool) == []


@pytest.mark.parametrize(
    "rebind",
    [
        "if condition:\n        conn = other",
        "try:\n        operation()\n    except Exception as conn:\n        pass",
        "match value:\n        case _ as conn:\n            pass",
        "with other as conn:\n        pass",
        "(conn := other)",
        "import sqlite3 as conn",
    ],
)
def test_control_flow_and_binding_forms_invalidate_connection(rebind: str) -> None:
    source = f"""
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]], other, condition, value):
    {rebind}
    with conn.cursor() as cursor:
        return cursor.fetchone()
"""
    assert _check(source) == []


def test_method_rebinding_invalidates_typed_pool_attribute() -> None:
    source = """
from psycopg import Connection
from psycopg_pool import ConnectionPool

class Store:
    def __init__(self, pool: ConnectionPool[Connection[tuple[object, ...]]]) -> None:
        self.pool = pool

    def load(self, other, condition):
        if condition:
            self.pool = other
        with self.pool.connection() as conn, conn.cursor() as cursor:
            return cursor.fetchone()
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "initializer",
    [
        "if condition:\n            self.pool = pool",
        "if condition:\n            return\n        self.pool = pool",
    ],
)
def test_constructor_requires_unconditional_pool_assignment(initializer: str) -> None:
    source = f"""
from psycopg import Connection
from psycopg_pool import ConnectionPool

class Store:
    pool = OtherPool()

    def __init__(self, pool: ConnectionPool[Connection[tuple[object, ...]]], condition):
        {initializer}

    def load(self):
        with self.pool.connection() as conn, conn.cursor() as cursor:
            return cursor.fetchone()
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "rebind",
    [
        "pool = make_unknown_pool()",
        "if condition:\n            pool = make_unknown_pool()",
    ],
)
def test_constructor_pool_parameter_must_remain_unmodified(rebind: str) -> None:
    source = f"""
from psycopg import Connection
from psycopg_pool import ConnectionPool

class Store:
    def __init__(self, pool: ConnectionPool[Connection[tuple[object, ...]]], condition):
        {rebind}
        self.pool = pool

    def load(self):
        with self.pool.connection() as conn, conn.cursor() as cursor:
            return cursor.fetchone()
"""
    assert _check(source) == []


def test_duplicate_initializers_abstain_from_pool_provenance() -> None:
    source = """
from psycopg import Connection
from psycopg_pool import ConnectionPool

class Store:
    def __init__(self, pool: ConnectionPool[Connection[tuple[object, ...]]]):
        self.pool = pool

    def __init__(self):
        self.pool = OtherPool()

    def load(self):
        with self.pool.connection() as conn, conn.cursor() as cursor:
            return cursor.fetchone()
"""
    assert _check(source) == []


def test_property_descriptor_invalidates_pool_storage_proof() -> None:
    source = """
from psycopg import Connection
from psycopg_pool import ConnectionPool

class Store:
    def __init__(self, pool: ConnectionPool[Connection[tuple[object, ...]]]):
        self.pool = pool

    @property
    def pool(self):
        return OtherPool()

    @pool.setter
    def pool(self, value):
        pass

    def load(self):
        with self.pool.connection() as conn, conn.cursor() as cursor:
            return cursor.fetchone()
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "replacement",
    [
        "self.pool = pool",
        "del self.pool",
        'setattr(self, "pool", pool)',
    ],
)
def test_cross_method_pool_mutation_invalidates_constructor_proof(replacement: str) -> None:
    source = f"""
from psycopg import Connection
from psycopg_pool import ConnectionPool

class Store:
    def __init__(self, pool: ConnectionPool[Connection[tuple[object, ...]]]):
        self.pool = pool

    def replace_pool(self, pool):
        {replacement}

    def load(self):
        with self.pool.connection() as conn, conn.cursor() as cursor:
            return cursor.fetchone()
"""
    assert _check(source) == []


def test_future_connection_binding_does_not_leak_backward() -> None:
    source = """
import psycopg

def load(other, dsn: str):
    with other.cursor() as cursor:
        row = cursor.fetchone()
    with psycopg.connect(dsn) as other:
        pass
    return row
"""
    assert _check(source) == []


def test_same_line_factory_assignment_uses_column_order() -> None:
    safe = """
import psycopg
from psycopg.rows import class_row

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        cursor.row_factory = class_row(TaskRow); return cursor.fetchone()
"""
    unsafe = """
import psycopg
from psycopg.rows import class_row, tuple_row

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor(row_factory=class_row(TaskRow)) as cursor:
        cursor.row_factory = tuple_row; return cursor.fetchone()
"""
    assert _check(safe) == []
    assert len(_check(unsafe)) == 1


def test_multi_hop_alias_escapes_but_transformed_alias_does_not() -> None:
    unchanged = """
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        row = cursor.fetchone()
        result = row
        return result
"""
    transformed = """
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        row = cursor.fetchone()
        row[0] = normalize(row[0])
        result = row
        return result
"""
    aliased_then_transformed = """
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        rows = cursor.fetchall()
        result = rows
        rows.reverse()
        return result
"""
    assert len(_check(unchanged)) == 1
    assert _check(transformed) == []
    assert _check(aliased_then_transformed) == []


def test_augmented_assignment_transforms_positional_result() -> None:
    source = """
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        rows = cursor.fetchall()
        rows += [("fallback",)]
        return rows
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "mutation",
    [
        "removed = rows.pop()",
        "assert rows.pop()",
        "print(rows.pop())",
        "if rows.pop():\n            pass",
    ],
)
def test_nested_mutating_call_transforms_positional_result(mutation: str) -> None:
    source = f"""
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        rows = cursor.fetchall()
        {mutation}
        return rows
"""
    assert _check(source) == []


def test_non_falling_loop_body_does_not_leak_alias_state() -> None:
    for_loop = """
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]], values):
    with conn.cursor() as cursor:
        result = make_named()
        for value in values:
            row = cursor.fetchone()
            result = row
            return make_named()
        return result
"""
    while_loop = """
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]], condition):
    with conn.cursor() as cursor:
        result = make_named()
        while condition:
            row = cursor.fetchone()
            result = row
            return make_named()
        return result
"""
    assert _check(for_loop) == []
    assert _check(while_loop) == []


def test_chained_alias_assignment_preserves_escape_origin() -> None:
    source = """
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        row = alias = cursor.fetchone()
        return alias
"""
    assert len(_check(source)) == 1


def test_alias_lineage_does_not_cross_sibling_branches() -> None:
    impossible_escape = """
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]], condition: bool):
    with conn.cursor() as cursor:
        row = make_named()
        result = make_named()
        if condition:
            row = cursor.fetchone()
        else:
            result = row
        return result
"""
    possible_escape = """
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]], condition: bool):
    with conn.cursor() as cursor:
        row = cursor.fetchone()
        if condition:
            result = row
        else:
            result = transform(row)
        return result
"""
    assert _check(impossible_escape) == []
    assert len(_check(possible_escape)) == 1


def test_conditional_mutation_preserves_the_unmodified_escape_path() -> None:
    source = """
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]], condition):
    with conn.cursor() as cursor:
        row = cursor.fetchone()
        alias = row
        if condition:
            alias.append("derived")
        return row
"""
    assert len(_check(source)) == 1


def test_guarded_wildcard_match_is_not_assumed_exhaustive() -> None:
    source = """
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]], value, condition):
    with conn.cursor() as cursor:
        row = cursor.fetchone()
        match value:
            case _ if condition:
                row = transform(row)
        return row
"""
    assert len(_check(source)) == 1


@pytest.mark.parametrize("loop", ["for value in values:", "while values:"])
def test_non_falling_loop_else_makes_following_return_unreachable(loop: str) -> None:
    source = f"""
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]], values):
    with conn.cursor() as cursor:
        result = make_named()
        {loop}
            row = cursor.fetchone()
            result = row
        else:
            return make_named()
        return result
"""
    assert _check(source) == []


@pytest.mark.parametrize("abrupt", ["break", "continue"])
def test_abrupt_loop_control_stops_unreachable_alias_flow(abrupt: str) -> None:
    source = f"""
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]], values):
    with conn.cursor() as cursor:
        result = make_named()
        for value in values:
            row = cursor.fetchone()
            {abrupt}
            result = row
        return result
"""
    assert _check(source) == []


def test_raise_stops_unreachable_alias_flow() -> None:
    source = """
from psycopg import Connection

def load(conn: Connection[tuple[object, ...]]):
    with conn.cursor() as cursor:
        result = make_named()
        row = cursor.fetchone()
        raise RuntimeError
        result = row
        return result
"""
    assert _check(source) == []


@pytest.mark.parametrize(
    "shadow",
    [
        "def tuple_row(cursor):\n        return cursor",
        "class tuple_row:\n        pass",
        "from custom_rows import tuple_row",
    ],
)
def test_function_local_binding_shadows_imported_factory(shadow: str) -> None:
    source = f"""
from psycopg import Connection
from psycopg.rows import tuple_row

def load(conn: Connection[tuple[object, ...]]):
    {shadow}
    with conn.cursor(row_factory=tuple_row) as cursor:
        return cursor.fetchone()
"""
    assert _check(source) == []


def test_locally_shadowed_psycopg_connect_abstains() -> None:
    module = """
import psycopg

def load(psycopg):
    with psycopg.connect() as conn, conn.cursor() as cursor:
        return cursor.fetchone()
"""
    direct = """
from psycopg import connect

def load(connect):
    with connect() as conn, conn.cursor() as cursor:
        return cursor.fetchone()
"""
    assert _check(module) == []
    assert _check(direct) == []


def test_nested_function_does_not_escape_outer_cursor() -> None:
    source = """
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        def inner():
            return cursor.fetchone()
        return inner
"""
    assert _check(source) == []


def test_exact_suppression_on_cursor_or_fetch() -> None:
    cursor_suppressed = """
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:  # sarj-noqa: SARJ414 - compatibility tuple
        return cursor.fetchone()
"""
    fetch_suppressed = """
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        return cursor.fetchone()  # sarj-noqa: SARJ414 - compatibility tuple
"""
    assert _check(cursor_suppressed) == []
    assert _check(fetch_suppressed) == []


def test_excludes_tests_migrations_generated_and_malformed_source() -> None:
    source = """
import psycopg

def load(dsn: str):
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        return cursor.fetchone()
"""
    assert _check(source, "tests/test_store.py") == []
    assert _check(source, "testing/db_helpers.py") == []
    assert _check(source, "src/test_utils/db.py") == []
    assert _check(source, "src/fakes/db.py") == []
    assert _check(source, "migrations/001.py") == []
    assert _check(f"# @generated\n{source}") == []
    assert _check("def broken(") == []


def test_large_irrelevant_file_stays_bounded() -> None:
    source = "\n".join(f"value_{index} = {index}" for index in range(5_000))
    assert _check(source) == []


@pytest.mark.parametrize("example", NoPositionalPsycopgRowEscape.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count
