from pathlib import Path

import pytest

from sarj_python_lint.rule_base import Diagnostic, RuleExample, is_suppressed
from sarj_python_lint.rules.store_insert_requires_on_conflict import (
    StoreInsertRequiresOnConflict,
)


def _check(source: str, path: str = "foo_store.py") -> list[Diagnostic]:
    return StoreInsertRequiresOnConflict().check(Path(path), source)


_PUBLIC_EXAMPLES = StoreInsertRequiresOnConflict.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(e.example_id for e in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(_check(focus.source, str(focus.path))) == example.expected_count


def _count(source: str, path: str = "foo_store.py") -> int:
    return len(_check(source, path))


# Positive — a bare write with no ON CONFLICT must fire exactly once.          #

FIRES = [
    pytest.param('q = "INSERT INTO t (id) VALUES (%s)"', id="bare_values"),
    pytest.param(
        'await cur.execute("INSERT INTO task (id) VALUES (%s)", (x,))',
        id="in_execute_call",
    ),
    pytest.param('q = "INSERT INTO t DEFAULT VALUES"', id="default_values"),
    pytest.param(
        'q = "INSERT INTO archive (id) SELECT id FROM task WHERE done"',
        id="insert_select",
    ),
    pytest.param(
        'q = "INSERT INTO t (id) VALUES (%s) RETURNING id"',
        id="returning_without_conflict_still_fires",
    ),
    pytest.param(
        'q = "insert into t (id) values (%s)"',
        id="all_lowercase",
    ),
    pytest.param(
        'q = "InSeRt InTo t (id) VaLuEs (%s)"',
        id="mixed_case",
    ),
    pytest.param(
        'q = "INSERT   INTO   t (id)   VALUES (%s)"',
        id="extra_whitespace_between_keywords",
    ),
    pytest.param(
        'q = "INSERT\\tINTO t (id)\\nVALUES (%s)"',
        id="tab_newline_between_keywords",
    ),
    pytest.param(
        'q = "INSERT INTO t ({}) VALUES ({})".format(a, b)',
        id="format_braces_are_literal_text",
    ),
    pytest.param(
        'q = f"INSERT INTO t (id) VALUES ({value})"',
        id="fstring_interpolation_after_values",
    ),
    pytest.param(
        'q = "INSERT INTO t (id) " + "VALUES (%s)"',
        id="explicit_plus_concat",
    ),
    pytest.param(
        'q = ("INSERT INTO t (id) " "VALUES (%s)")',
        id="implicit_adjacent_concat",
    ),
    pytest.param(
        'q = "INSERT INTO t (id) VALUES (%s) -- ON CONFLICT DO NOTHING"',
        id="on_conflict_in_line_comment_does_not_excuse",
    ),
    pytest.param(
        'q = "INSERT INTO t (id) VALUES (%s) /* ON CONFLICT DO NOTHING */"',
        id="on_conflict_in_block_comment_does_not_excuse",
    ),
    pytest.param(
        '''q = """
    INSERT INTO t (id) VALUES (%s)
    -- ON CONFLICT (id) DO NOTHING would go here
    """''',
        id="on_conflict_commented_out_multiline",
    ),
]


@pytest.mark.parametrize("src", FIRES)
def test_fires_once(src: str) -> None:
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ018"
    assert "upsert" in diags[0].message.lower()


# Negative — legitimate / exempt SQL must not fire.                           #

CLEAN = [
    pytest.param(
        'def create_user():\n    q = "INSERT INTO users (id) VALUES (%s)"',
        id="ordinary-create-contract",
    ),
    pytest.param(
        'def seed():\n    q = "INSERT INTO users (id) SELECT %s WHERE NOT EXISTS (SELECT 1 FROM users)"',
        id="insert-select-where-not-exists",
    ),
    pytest.param(
        'q = "INSERT INTO t (id) VALUES (%s) ON CONFLICT DO NOTHING"',
        id="on_conflict_do_nothing",
    ),
    pytest.param(
        'q = "INSERT INTO t (id) VALUES (%s) ON CONFLICT (id) DO UPDATE SET id=EXCLUDED.id"',
        id="on_conflict_do_update",
    ),
    pytest.param(
        'q = "INSERT INTO t (id) VALUES (%s) On Conflict Do Nothing"',
        id="on_conflict_mixed_case",
    ),
    pytest.param(
        'q = "INSERT INTO t (id) VALUES (%s)\\nON CONFLICT DO NOTHING"',
        id="on_conflict_on_next_line",
    ),
    pytest.param(
        'q = ("INSERT INTO t (id) VALUES (%s) " "ON CONFLICT (id) DO NOTHING")',
        id="on_conflict_on_concatenated_chunk",
    ),
    pytest.param(
        'q = "INSERT INTO t (id) " + "VALUES (%s) ON CONFLICT DO NOTHING"',
        id="on_conflict_on_plus_concat_chunk",
    ),
    pytest.param('await cur.execute("SELECT id FROM task WHERE id = %s")', id="select_only"),
    pytest.param('q = "WITH x AS (SELECT 1) SELECT * FROM task"', id="cte_select"),
    pytest.param('q = "UPDATE t SET id = %s WHERE id = %s"', id="update_only"),
    pytest.param('q = "DELETE FROM t WHERE id = %s"', id="delete_only"),
    pytest.param(
        'q = "INSERT INTO t"',
        id="insert_into_without_values_is_incomplete",
    ),
    pytest.param(
        'q = "SELECT id FROM t -- INSERT INTO t (id) VALUES (1)"',
        id="insert_in_line_comment",
    ),
    pytest.param(
        'q = "/* INSERT INTO t (id) VALUES (1) */ SELECT 1 FROM t"',
        id="insert_in_block_comment",
    ),
    pytest.param("mylist.insert(0, x)", id="python_list_insert_method"),
    pytest.param("self.buffer.insert(idx, row)", id="python_insert_method_call"),
    pytest.param('msg = "Please insert your card"', id="prose_insert_word"),
    pytest.param(
        'doc = "See the docs about INSERT INTO tables in general"',
        id="prose_insert_into_no_values",
    ),
    pytest.param('"""Module docstring mentioning insert semantics."""', id="docstring_prose"),
    pytest.param("", id="empty_file"),
    pytest.param("   \n\n\t", id="whitespace_only"),
    pytest.param("def (:::", id="syntax_error"),
    pytest.param("x = 1 +", id="syntax_error_incomplete_binop"),
]


@pytest.mark.parametrize("src", CLEAN)
def test_does_not_fire(src: str) -> None:
    assert _check(src) == []


def test_replay_contract_method_without_conflict_handling_fires() -> None:
    src = """
async def enqueue_call(call_id: str) -> None:
    await cursor.execute("INSERT INTO call_queue (call_id) VALUES (%s)", (call_id,))
"""
    assert _count(src) == 1


# Multiline reporting                                                          #


def test_multiline_triple_quoted_reports_string_start_line() -> None:
    src = '''
async def enqueue_task(self):
    await cur.execute(
        SQL("""
        INSERT INTO task (organization_id, status)
        VALUES (%s, %s)
        RETURNING id
        """).format(),
        (org_id, status),
    )
'''
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 4


def test_line_and_col_reported_one_based() -> None:
    src = 'q = "INSERT INTO t VALUES (1)"'
    diags = _check(src)
    assert (diags[0].line, diags[0].col) == (1, 5)


def test_plus_concat_reports_left_operand_position() -> None:
    src = 'q = (\n    "INSERT INTO t "\n    + "VALUES (1)"\n)'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2
    assert diags[0].col == 5


# Multiple findings                                                            #


def test_each_insert_flagged_separately_and_sorted() -> None:
    src = (
        'a = "INSERT INTO b (id) VALUES (2)"\n'
        'b = "INSERT INTO a (id) VALUES (1)"\n'
        'c = "INSERT INTO c (id) VALUES (3)"\n'
    )
    diags = _check(src)
    assert len(diags) == 3
    assert [d.line for d in diags] == [1, 2, 3]


def test_multiple_bare_inserts_in_one_literal_report_once() -> None:
    src = 'q = "INSERT INTO a VALUES (1); INSERT INTO b VALUES (2)"'
    assert _count(src) == 1


def test_mixed_clean_and_dirty_only_flags_dirty() -> None:
    src = 'good = "INSERT INTO t (id) VALUES (1) ON CONFLICT DO NOTHING"\nbad = "INSERT INTO t (id) VALUES (2)"\n'
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2


# Suppression                                                                 #


def test_diagnostic_line_is_suppressible_by_sarj_noqa() -> None:
    src = 'q = "INSERT INTO ch_events (id) VALUES (%s)"  # sarj-noqa: SARJ018 — ClickHouse has no upsert'
    diags = _check(src)
    assert len(diags) == 1
    assert is_suppressed(src.splitlines(), diags[0].line, diags[0].code)


# Path gate — the rule fires only on store-layer modules (`*_store.py` basename # or a file under a `stores/` directory).


@pytest.mark.parametrize("path", ["foo_store.py", "stores/foo.py"])
def test_store_file_flagged(path: str) -> None:
    assert _count('q = "INSERT INTO t (id) VALUES (1)"', path) == 1


@pytest.mark.parametrize("path", ["handler.py", "services/handler.py", "app/views.py", "random.py"])
def test_nonstore_file_not_flagged(path: str) -> None:
    assert _count('q = "INSERT INTO t (id) VALUES (1)"', path) == 0


# Known limitations (xfail) — documented false negatives.                      #


@pytest.mark.xfail(
    reason="f-string interpolation between INSERT INTO and VALUES splits the "
    "literal into fragments, so neither AST Constant matches INSERT...VALUES; "
    "the write is silently missed.",
    strict=True,
)
def test_fstring_interpolation_between_keywords_is_missed() -> None:
    src = 'q = f"INSERT INTO {table} (id) VALUES (%s)"'
    assert _count(src) == 1


@pytest.mark.xfail(
    reason="ON CONFLICT is searched across the whole literal, not per-statement, "
    "so an ON CONFLICT in one statement excuses a bare INSERT in another "
    "within the same string.",
    strict=True,
)
def test_on_conflict_in_unrelated_statement_wrongly_excuses() -> None:
    src = 'q = "UPDATE x SET y = 1 ON CONFLICT DO NOTHING; INSERT INTO t (id) VALUES (%s)"'
    assert _count(src) == 1


# New passing regressions — correct behavior on previously untested shapes.    #

NEW_FIRES = [
    pytest.param(
        'q = "WITH x AS (SELECT 1) INSERT INTO t (id) SELECT id FROM x"',
        id="data_modifying_cte_insert_select_fires",
    ),
    pytest.param(
        'q = "INSERT INTO t (id) VALUES(%s)"',
        id="values_with_no_space_before_paren",
    ),
    pytest.param(
        'q = "INSERT INTO t " + "(id) " + "VALUES (1)"',
        id="three_operand_plus_concat_fires_once",
    ),
    pytest.param(
        'q = "INSERT INTO t VALUES (" + str(x) + ")"',
        id="keywords_intact_in_one_constant_of_nonfoldable_concat",
    ),
]


@pytest.mark.parametrize("src", NEW_FIRES)
def test_new_fires_once(src: str) -> None:
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].code == "SARJ018"


# String-literal awareness: an ON CONFLICT / `--` inside a quoted VALUE no       # longer excuses or falsely trips a finding.


def test_on_conflict_inside_inserted_string_value_wrongly_excuses() -> None:
    src = "q = \"INSERT INTO t (msg) VALUES ('ON CONFLICT DO NOTHING')\""
    assert _count(src) == 1


def test_double_dash_in_string_value_strips_real_on_conflict() -> None:
    src = "q = \"INSERT INTO t (c) VALUES ('a--b') ON CONFLICT DO NOTHING\""
    assert _count(src) == 0


@pytest.mark.xfail(
    reason="A runtime `+`-concatenated expression between INSERT INTO and VALUES "
    "splits the keywords across two constants, so neither matches and the write is "
    "silently missed.",
    strict=True,
)
def test_plus_concat_runtime_value_between_keywords_is_missed() -> None:
    src = 'q = "INSERT INTO t " + table + " (id) VALUES (%s)"'
    assert _count(src) == 1


# First-party review regression: a test file is never a store module.


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("tests/store/test_sip_connection_store.py", id="test-prefixed-store-name"),
        pytest.param("foo_store_test.py", id="test-suffixed-store-name"),
        pytest.param("tests/fixtures.py", id="under-tests-dir"),
        pytest.param("stores/conftest.py", id="conftest-under-stores"),
    ],
)
def test_test_files_are_not_store_modules(path: str) -> None:
    """Evidence: a first-party store test that seeds one row per test."""
    src = 'q = "INSERT INTO phone_provider (provider_name) VALUES (%s) RETURNING id::text"'
    assert _count(src, path) == 0


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("sip_connection_store.py", id="store-module"),
        pytest.param("stores/phone_provider_store.py", id="under-stores-dir"),
    ],
)
def test_production_store_modules_still_fire(path: str) -> None:
    src = 'q = "INSERT INTO phone_provider (provider_name) VALUES (%s) RETURNING id::text"'
    assert _count(src, path) == 1


# Cross-package parity with SARJ105 and the TS twin                            # (`packages/sql/.../insert_requires_on_conflict.py`,                          # `packages/typescript/src/rules/store-insert-requires-on-conflict.ts`).

ALREADY_IDEMPOTENT = [
    pytest.param(
        'q = "INSERT INTO t (a) VALUES (%s) ON CONFLICT (a) DO NOTHING"',
        id="postgres_on_conflict",
    ),
    pytest.param(
        'q = "INSERT INTO t (a, b) VALUES (%s, %s) ON DUPLICATE KEY UPDATE b = VALUES(b)",',
        id="mysql_on_duplicate_key",
    ),
    pytest.param('q = "INSERT OR IGNORE INTO t (a) VALUES (?)"', id="sqlite_insert_or_ignore"),
    pytest.param('q = "INSERT OR REPLACE INTO t (a) VALUES (?)"', id="sqlite_insert_or_replace"),
]


@pytest.mark.parametrize("source", ALREADY_IDEMPOTENT)
def test_every_idempotent_insert_form_is_excused(source: str) -> None:
    """A MySQL upsert used to fire here and be clean in TS — the same write, two verdicts."""
    assert _count(source) == 0


def test_insert_or_abort_is_not_excused() -> None:
    """`OR IGNORE`/`OR REPLACE` survive replay; `OR ABORT` does not, so it still fires."""
    assert _count('q = "INSERT OR ABORT INTO t (a) VALUES (?)"') == 1


def test_prose_mentioning_insert_into_and_values_does_not_fire() -> None:
    """The old `.*?` under DOTALL matched `insert into ..."""
    src = 'msg = "failed to insert into the queue: values were rejected by the broker"'
    assert _count(src) == 0


def test_insert_keyword_without_a_write_verb_does_not_fire() -> None:
    assert _count('q = "GRANT INSERT ON TABLE t TO app_role"') == 0


def test_insert_inside_dollar_quoted_body_is_not_exempt() -> None:
    src = 'q = "DO $$ BEGIN INSERT INTO t (a) VALUES (1); END $$"'
    assert _count(src) == 1
