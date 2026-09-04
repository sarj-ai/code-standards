from pathlib import Path
import textwrap
from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.rule_base import RuleExample, Severity
from sarj_python_lint.rules.prefer_class_row import PreferClassRow


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Diagnostic


_PATH = Path("app/task_store.py")
_IMPORT = "from psycopg.rows import dict_row\n\n"


def _check(source: str, path: Path = _PATH) -> list[Diagnostic]:
    return PreferClassRow().check(path, _IMPORT + textwrap.dedent(source))


_PUBLIC_EXAMPLES = PreferClassRow.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(PreferClassRow().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    ("async_prefix", "await_prefix"),
    [("", ""), ("async ", ""), ("async ", "await ")],
    ids=["sync", "async-sync-driver", "async"],
)
def test_fetchone_then_model_validate_fires(async_prefix: str, await_prefix: str) -> None:
    source = f"""
        {async_prefix}def load(conn):
            with conn.cursor(row_factory=dict_row) as cursor:
                row = {await_prefix}cursor.fetchone()
                return Task.model_validate(row)
    """
    [diagnostic] = _check(source)
    assert diagnostic.code == "SARJ013"
    assert diagnostic.severity is Severity.WARNING
    assert "class_row(Task)" in diagnostic.message


def test_async_cursor_then_model_constructor_fires() -> None:
    source = """
        async def load(conn):
            async with conn.cursor(row_factory=dict_row) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                return Task(**row)
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize("container", ["[]", "set()", "()"])
def test_fetchall_model_comprehensions_fire(container: str) -> None:
    if container == "[]":
        conversion = "[Task(**row) for row in rows]"
    elif container == "set()":
        conversion = "{Task(**row) for row in rows}"
    else:
        conversion = "tuple(Task(**row) for row in rows)"
    source = f"""
        async def load(conn):
            async with conn.cursor(row_factory=dict_row) as cursor:
                rows = await cursor.fetchall()
                return {conversion}
    """
    assert len(_check(source)) == 1


def test_fetchmany_generator_passed_to_extend_fires() -> None:
    source = """
        async def load(conn):
            async with conn.cursor(row_factory=dict_row) as cursor:
                rows = await cursor.fetchmany(100)
                result.extend(Task(**row) for row in rows)
                return result
    """
    assert len(_check(source)) == 1


def test_assigned_cursor_fires() -> None:
    source = """
        def load(conn):
            cursor = conn.cursor(row_factory=dict_row)
            row = cursor.fetchone()
            return Task(**row)
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    ("header", "factory"),
    [
        ("from psycopg.rows import dict_row as dr", "dr"),
        ("import psycopg.rows as rows", "rows.dict_row"),
        ("from psycopg import rows as row_factories", "row_factories.dict_row"),
        ("import psycopg", "psycopg.rows.dict_row"),
        ("import psycopg.rows", "psycopg.rows.dict_row"),
    ],
)
def test_import_proven_factory_spellings_fire(header: str, factory: str) -> None:
    source = textwrap.dedent(f"""\
        {header}

        def load(conn):
            with conn.cursor(row_factory={factory}) as cursor:
                row = cursor.fetchone()
                return Task(**row)
        """)
    assert len(PreferClassRow().check(_PATH, source)) == 1


def test_qualified_model_name_is_preserved_in_message() -> None:
    source = """
        def load(conn):
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.fetchone()
                return models.Task(**row)
    """
    [diagnostic] = _check(source)
    assert "class_row(models.Task)" in diagnostic.message


def test_diagnostic_points_to_factory() -> None:
    source = """
        def load(conn):
            with conn.cursor(
                row_factory=dict_row,
            ) as cursor:
                row = cursor.fetchone()
                return Task(**row)
    """
    [diagnostic] = _check(source)
    assert (diagnostic.line, diagnostic.col) == (6, 21)


@pytest.mark.parametrize(
    "body",
    [
        "return row",
        "return dict(row)",
        "return {'id': row['id']}",
        "return Response(id=row['id'])",
        "return Task(id=row['task_id'])",
    ],
)
def test_intentional_or_transformed_dictionary_results_are_clean(body: str) -> None:
    source = f"""
        def load(conn):
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.fetchone()
                {body}
    """
    assert _check(source) == []


def test_mutated_row_before_model_conversion_is_clean() -> None:
    source = """
        def load(conn):
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.fetchone()
                row["status"] = normalize(row["status"])
                return Task(**row)
    """
    assert _check(source) == []


def test_reassigned_row_before_model_conversion_is_clean() -> None:
    source = """
        def load(conn):
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.fetchone()
                row = transform(row)
                return Task(**row)
    """
    assert _check(source) == []


def test_one_cursor_used_for_multiple_models_is_clean() -> None:
    source = """
        def load(conn):
            with conn.cursor(row_factory=dict_row) as cursor:
                first = cursor.fetchone()
                a = Task(**first)
                second = cursor.fetchone()
                b = User(**second)
                return a, b
    """
    assert _check(source) == []


def test_one_cursor_used_for_a_raw_shape_and_a_model_is_clean() -> None:
    source = """
        def load(conn):
            with conn.cursor(row_factory=dict_row) as cursor:
                count_row = cursor.fetchone()
                total = count_row["count"]
                row = cursor.fetchone()
                return Task(**row), total
    """
    assert _check(source) == []


def test_unrelated_fetches_and_sql_strings_do_not_mask_conversion() -> None:
    source = """
        def load(conn, other):
            other.fetchone()
            other.fetchall()
            query = "SELECT count(*) FROM audit"
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.fetchone()
                return Task(**row)
    """
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "build(row_factory=dict_row)",
        "@register(row_factory=dict_row)\ndef load():\n    pass",
        "class Store(Base, row_factory=dict_row):\n    pass",
        "psycopg.connect(dsn, row_factory=dict_row)",
        "conn.row_factory = dict_row",
    ],
)
def test_unproven_psycopg_consumers_are_clean(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [Path("tests/test_task_store.py"), Path("app/migrations/load.py"), Path("app/generated/store.py")],
    ids=["test", "migration", "generated"],
)
def test_excluded_paths_are_clean(path: Path) -> None:
    source = """
        def load(conn):
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.fetchone()
                return Task(**row)
    """
    assert _check(source, path) == []


def test_generated_header_is_clean() -> None:
    source = "# This file is generated. Do not edit.\n" + _IMPORT + textwrap.dedent("""
        def load(conn):
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.fetchone()
                return Task(**row)
    """)
    assert PreferClassRow().check(_PATH, source) == []


def test_unimported_dict_row_is_clean() -> None:
    source = """
def load(conn):
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.fetchone()
        return Task(**row)
"""
    assert PreferClassRow().check(_PATH, source) == []


def test_module_rebound_import_is_clean() -> None:
    source = """
from psycopg.rows import dict_row
dict_row = local_factory

def load(conn):
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.fetchone()
        return Task(**row)
"""
    assert PreferClassRow().check(_PATH, source) == []


def test_function_parameter_shadowing_is_local() -> None:
    source = """
from psycopg.rows import dict_row

def unrelated(dict_row):
    return dict_row

def load(conn):
    with conn.cursor(row_factory=dict_row) as cursor:
        row = cursor.fetchone()
        return Task(**row)
"""
    assert len(PreferClassRow().check(_PATH, source)) == 1


def test_local_rebinding_is_clean() -> None:
    source = """
        def load(conn):
            dict_row = local_factory
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.fetchone()
                return Task(**row)
    """
    assert _check(source) == []


def test_nested_scope_conversion_does_not_attach_to_outer_cursor() -> None:
    source = """
        def load(conn):
            with conn.cursor(row_factory=dict_row) as cursor:
                row = cursor.fetchone()
                def convert():
                    return Task(**row)
                return convert
    """
    assert _check(source) == []


@pytest.mark.parametrize("source", ["", "# comment\n", "def broken(:\n"])
def test_empty_or_invalid_source_is_clean(source: str) -> None:
    assert PreferClassRow().check(_PATH, source) == []
