from pathlib import Path

import pytest

from sarj_python_lint.rule_base import Diagnostic, RuleExample, is_suppressed
from sarj_python_lint.rules.store_insert_requires_on_conflict import StoreInsertRequiresOnConflict


def _check(source: str, path: str = "foo_store.py") -> list[Diagnostic]:
    return StoreInsertRequiresOnConflict().check(Path(path), source)


def _count(source: str, path: str = "foo_store.py") -> int:
    return len(_check(source, path))


_PUBLIC_EXAMPLES = StoreInsertRequiresOnConflict.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO task (id) VALUES (%s)",
        "INSERT INTO task DEFAULT VALUES",
        "INSERT INTO task (id) SELECT id FROM pending",
        "INSERT INTO task (id) VALUES (%s) RETURNING id",
        "insert into task (id) values (%s)",
        "INSERT   INTO task (id) VALUES(%s)",
        "INSERT OR ABORT INTO task (id) VALUES (?)",
        "UPDATE x SET y = 1 ON CONFLICT DO NOTHING; INSERT INTO task (id) VALUES (%s)",
        "INSERT INTO task (id) VALUES (%s) ON CONFLICT (id)",
        "INSERT INTO task (id) SELECT id FROM pending WHERE NOT EXISTS (SELECT 1 FROM other)",
    ],
)
def test_replay_named_execute_requires_duplicate_policy(sql: str) -> None:
    source = f'def ensure_task(cursor):\n    cursor.execute("{sql}")\n'
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "SARJ018"
    assert "duplicate policy" in diagnostics[0].message


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO task (id) VALUES (%s) ON CONFLICT DO NOTHING",
        "INSERT INTO task (id) VALUES (%s) ON CONFLICT (id) DO UPDATE SET id = EXCLUDED.id",
        "INSERT INTO task (id) VALUES (%s) ON DUPLICATE KEY UPDATE id = VALUES(id)",
        "INSERT OR IGNORE INTO task (id) VALUES (?)",
        "INSERT OR REPLACE INTO task (id) VALUES (?)",
        "INSERT INTO task (id) SELECT id FROM pending WHERE NOT EXISTS (SELECT 1 FROM task)",
    ],
)
def test_explicit_duplicate_policy_is_accepted(sql: str) -> None:
    source = f'def ensure_task(cursor):\n    cursor.execute("{sql}")\n'
    assert _check(source) == []


@pytest.mark.parametrize(
    "name",
    ["ensure_task", "enqueue_task", "record_once", "get_or_create_task", "create_if_absent", "insert_if_absent"],
)
def test_explicit_replay_contract_names_are_checked(name: str) -> None:
    source = f'def {name}(cursor):\n    cursor.execute("INSERT INTO task (id) VALUES (1)")\n'  # ruff: ignore[hardcoded-sql-expression] -- analyzer fixture
    assert _count(source) == 1


@pytest.mark.parametrize("name", ["create_task", "seed_tasks", "migrate_tasks", "schedule_task", "upsert_task"])
def test_ambiguous_or_insert_only_names_are_not_inferred(name: str) -> None:
    source = f'def {name}(cursor):\n    cursor.execute("INSERT INTO task (id) VALUES (1)")\n'  # ruff: ignore[hardcoded-sql-expression] -- analyzer fixture
    assert _check(source) == []


def test_sql_shaped_local_binding_is_checked() -> None:
    source = (
        'def ensure_task(cursor):\n    insert_sql = "INSERT INTO task (id) VALUES (1)"\n'
        "    cursor.execute(insert_sql)\n"
    )
    assert _count(source) == 1


@pytest.mark.parametrize("binding", ["q", "query", "sql", "statement", "stmt", "insert_query"])
def test_supported_sql_binding_names_are_checked(binding: str) -> None:
    source = (
        f'def ensure_task(cursor):\n    {binding} = "INSERT INTO task (id) VALUES (1)"\n    cursor.execute({binding})\n'  # ruff: ignore[hardcoded-sql-expression] -- analyzer fixture
    )
    assert _count(source) == 1


def test_non_sql_local_binding_is_not_assumed_executable() -> None:
    source = 'def ensure_task():\n    message = "INSERT INTO task (id) VALUES (1)"\n'
    assert _check(source) == []


def test_unused_sql_shaped_binding_is_not_executable() -> None:
    source = 'def ensure_task():\n    query = "INSERT INTO task (id) VALUES (1)"\n    log(query)\n'
    assert _check(source) == []


def test_sql_looking_parameter_value_is_not_treated_as_query() -> None:
    source = """
def ensure_task(cursor):
    cursor.execute(
        "INSERT INTO log(message) VALUES (%s) ON CONFLICT DO NOTHING",
        ("INSERT INTO task(id) VALUES (1)",),
    )
"""
    assert _check(source) == []


def test_keyword_query_argument_is_checked() -> None:
    source = """
def ensure_task(cursor):
    cursor.prepare(sql="INSERT INTO task (id) VALUES (1)")
"""
    assert _count(source) == 1


def test_module_sql_constant_is_not_a_replay_contract() -> None:
    assert _check('QUERY = "INSERT INTO task (id) VALUES (1)"\n') == []


def test_docstring_and_error_prose_are_not_sql_execution() -> None:
    source = '''
def ensure_task():
    """Run INSERT INTO task (id) VALUES (1) after validation."""
    raise RuntimeError("Failed: INSERT INTO task (id) VALUES (1)")
'''
    assert _check(source) == []


def test_dynamic_conflict_format_fragment_abstains() -> None:
    source = """
def ensure_task(cursor):
    query = "INSERT INTO task (id) VALUES (%s) {on_conflict}".format(on_conflict=ON_CONFLICT_SQL)
"""
    assert _check(source) == []


def test_dynamic_conflict_fstring_fragment_abstains() -> None:
    source = """
def ensure_task(cursor):
    query = f"INSERT INTO task (id) VALUES (%s) {on_conflict_sql}"
"""
    assert _check(source) == []


def test_unrelated_dynamic_target_remains_checkable() -> None:
    source = """
def ensure_task(cursor, table):
    query = f"INSERT INTO {table} (id) VALUES (%s)"
    cursor.execute(query)
"""
    assert _count(source) == 1


def test_dynamic_duplicate_value_does_not_look_like_policy() -> None:
    source = """
def ensure_task(cursor, duplicate_id):
    cursor.execute(f"INSERT INTO task (id) VALUES ({duplicate_id})")
"""
    assert _count(source) == 1


def test_dynamic_upsert_table_does_not_look_like_policy() -> None:
    source = """
def ensure_task(cursor, upsert_table):
    cursor.execute(f"INSERT INTO {upsert_table} (id) VALUES (1)")
"""
    assert _count(source) == 1


def test_runtime_concatenated_target_is_checked() -> None:
    source = """
def ensure_task(cursor, table):
    cursor.execute("INSERT INTO " + table + " (id) VALUES (1)")
"""
    assert _count(source) == 1


@pytest.mark.parametrize("target", ['"task"', 'public."task"'])
def test_quoted_postgres_target_is_checked(target: str) -> None:
    source = f"def ensure_task(cursor):\n    cursor.execute('INSERT INTO {target} (id) VALUES (1)')\n"  # ruff: ignore[hardcoded-sql-expression] -- analyzer fixture
    assert _count(source) == 1


def test_quoted_same_target_guard_is_accepted() -> None:
    source = """
def ensure_task(cursor):
    cursor.execute(
        'INSERT INTO public."task" (id) SELECT 1 '
        'WHERE NOT EXISTS (SELECT 1 FROM public."task" WHERE id = 1)'
    )
"""
    assert _check(source) == []


def test_nested_callable_cannot_consume_outer_sql_binding() -> None:
    source = """
def ensure_task():
    query = "INSERT INTO task (id) VALUES (1)"
    def later(cursor):
        cursor.execute(query)
"""
    assert _check(source) == []


def test_comments_and_string_values_cannot_supply_policy() -> None:
    source = """
def ensure_task(cursor):
    cursor.execute("INSERT INTO task (message) VALUES ('ON CONFLICT DO NOTHING') -- ON CONFLICT DO NOTHING")
"""
    assert _count(source) == 1


def test_comment_markers_inside_value_do_not_mask_real_policy() -> None:
    source = """
def ensure_task(cursor):
    cursor.execute("INSERT INTO task (message) VALUES ('a--b') ON CONFLICT DO NOTHING")
"""
    assert _check(source) == []


def test_static_concatenation_is_checked_once() -> None:
    source = """
def ensure_task(cursor):
    query = "INSERT INTO task (id) " + "VALUES (%s)"
    cursor.execute(query)
"""
    assert _count(source) == 1


def test_multiline_diagnostic_points_to_literal_start() -> None:
    source = '''
async def ensure_task(cursor):
    await cursor.execute(
        SQL("""
        INSERT INTO task (id)
        VALUES (%s)
        """),
    )
'''
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert (diagnostics[0].line, diagnostics[0].col) == (4, 13)


def test_exact_suppression_is_honored_by_runner() -> None:
    source = """
def enqueue_event(cursor):
    query = "INSERT INTO events (id) VALUES (%s)"  # sarj-noqa: SARJ018 -- append-only event
    cursor.execute(query)
"""
    diagnostics = _check(source)
    assert len(diagnostics) == 1
    assert is_suppressed(source.splitlines(), diagnostics[0].line, diagnostics[0].code)


@pytest.mark.parametrize("path", ["foo_store.py", "stores/foo.py", "app/store.py"])
def test_store_paths_are_checked(path: str) -> None:
    source = 'def ensure_task(cursor):\n    cursor.execute("INSERT INTO task (id) VALUES (1)")\n'
    assert _count(source, path) == 1


@pytest.mark.parametrize("path", ["handler.py", "tests/foo_store.py", "foo_store_test.py", "stores/conftest.py"])
def test_nonstore_and_test_paths_are_excluded(path: str) -> None:
    source = 'def ensure_task(cursor):\n    cursor.execute("INSERT INTO task (id) VALUES (1)")\n'
    assert _check(source, path) == []


@pytest.mark.parametrize(
    ("path", "prefix"),
    [("generated_store.py", "# Generated by protoc\n"), ("stores/client.py", "# @generated\n")],
)
def test_generated_modules_are_excluded(path: str, prefix: str) -> None:
    source = f'{prefix}def ensure_task(cursor):\n    cursor.execute("INSERT INTO task (id) VALUES (1)")\n'  # ruff: ignore[hardcoded-sql-expression] -- analyzer fixture
    assert _check(source, path) == []


@pytest.mark.parametrize(
    "source",
    [
        "",
        "def (::::",
        "def ensure_task():\n    query = 'SELECT 1'\n",
        "def ensure_task():\n    values.insert(0, item)\n",
    ],
)
def test_non_candidates_are_clean(source: str) -> None:
    assert _check(source) == []
