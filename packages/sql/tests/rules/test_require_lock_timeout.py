from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rule_base import dbmate_directives, dbmate_transactional, has_dbmate_directive
from sarj_sql_lint.rules.require_lock_timeout import RequireLockTimeout


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


P = Path("supabase/migrations/001_schema.sql")


def _check(source: str, path: Path = P) -> list[Diagnostic]:
    return RequireLockTimeout().check(path, dedent(source))


_PUBLIC_EXAMPLES = RequireLockTimeout.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(example.example_id for example in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(RequireLockTimeout().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    "assignment",
    [
        "SET LOCAL lock_timeout = '3s';",
        "SET SESSION lock_timeout = '3s';",
        "SET  lock_timeout = '3s';",  # two spaces — the only form the old regex matched
        "SET lock_timeout = '3s';",  # the canonical single-space form
        "SET statement_timeout = '5s';",
        "SET lock_timeout TO '3s';",
        "SET lock_timeout='3s';",
        "set lock_timeout = '3s';",
    ],
)
def test_every_assignment_spelling_silences_the_rule(assignment: str) -> None:
    assert _check(f"{assignment}\nALTER TABLE users ADD COLUMN note TEXT;\n") == []


@pytest.mark.parametrize("boundary", ["-- migrate:down", "-- migrate:down transaction:false", "-- +goose Down"])
def test_up_timeout_does_not_leak_into_separately_executed_down_section(boundary: str) -> None:
    source = f"""
    -- migrate:up
    SET lock_timeout = '3s';
    ALTER TABLE users ADD COLUMN note TEXT;
    {boundary}
    ALTER TABLE users DROP COLUMN note;
    """

    (finding,) = _check(source)

    assert finding.line == 6


def test_each_migration_section_can_set_its_own_timeout() -> None:
    source = """
    -- migrate:up
    SET lock_timeout = '3s';
    ALTER TABLE users ADD COLUMN note TEXT;
    -- migrate:down
    SET lock_timeout = '3s';
    ALTER TABLE users DROP COLUMN note;
    """

    assert _check(source) == []


def test_down_like_text_inside_a_function_body_is_not_a_section_boundary() -> None:
    source = """
    SET lock_timeout = '3s';
    DO $body$
    -- migrate:down
    BEGIN
      NULL;
    END
    $body$;
    ALTER TABLE users ADD COLUMN note TEXT;
    """

    assert _check(source) == []


def test_zero_timeout_is_not_protection() -> None:
    assert len(_check("SET lock_timeout = 0;\nALTER TABLE users ADD COLUMN note TEXT;\n")) == 1


@pytest.mark.parametrize("value", ["'0.0s'", "'00ms'", "'0 min'", '"0"'])
def test_every_zero_spelling_is_not_protection(value: str) -> None:
    assert len(_check(f"SET lock_timeout = {value};\nALTER TABLE users ADD COLUMN note TEXT;\n")) == 1


@pytest.mark.parametrize(
    "prologue",
    [
        "-- SET lock_timeout = '3s';",  # line comment
        "/* SET lock_timeout = '3s'; */",  # block comment
        "INSERT INTO audit (sql) VALUES ('SET lock_timeout = ''3s''');",  # string literal
    ],
    ids=["line-comment", "block-comment", "string-literal"],
)
def test_a_timeout_that_is_only_mentioned_is_not_a_timeout_that_is_set(prologue: str) -> None:
    assert len(_check(f"{prologue}\nALTER TABLE users ADD COLUMN note TEXT;\n")) == 1


@pytest.mark.parametrize("value", ["'abc'", "'forever'", "''", "'none'"])
def test_a_value_that_is_not_an_interval_is_not_protection(value: str) -> None:
    assert len(_check(f"SET lock_timeout = {value};\nALTER TABLE t ADD COLUMN c INT;\n")) == 1


@pytest.mark.parametrize("value", ["'3s'", "'250ms'", "'1min'", "5000", "'2.5s'"])
def test_a_plausible_interval_is_protection(value: str) -> None:
    assert _check(f"SET lock_timeout = {value};\nALTER TABLE t ADD COLUMN c INT;\n") == []


def test_reset_undoes_a_timeout() -> None:
    src = "SET lock_timeout = '3s';\nRESET lock_timeout;\nALTER TABLE users ADD COLUMN note TEXT;\n"
    assert len(_check(src)) == 1


@pytest.mark.parametrize(
    "prologue",
    [
        "SET statement_timeout = '3s';\nRESET statement_timeout;",
        "SET statement_timeout = 0;",
        "SET statement_timeout = DEFAULT;",
    ],
    ids=["reset", "zero", "default"],
)
def test_statement_timeout_can_be_deactivated(prologue: str) -> None:
    assert len(_check(f"{prologue}\nALTER TABLE t ADD c INT;")) == 1


def test_similarly_named_setting_is_not_lock_timeout() -> None:
    assert len(_check("SET lock_timeout_ms = '3s';\nALTER TABLE t ADD COLUMN c INT;\n")) == 1


def test_one_finding_per_unprotected_run_not_per_statement() -> None:
    src = """
    ALTER TABLE a ADD COLUMN x INT;
    ALTER TABLE b ADD COLUMN y INT;
    CREATE INDEX idx_c ON c (id);
    DROP TABLE d;
    """
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 2


def test_one_assignment_protects_every_later_statement() -> None:
    src = """
    SET lock_timeout = '3s';
    ALTER TABLE a ADD COLUMN x INT;
    ALTER TABLE b ADD COLUMN y INT;
    CREATE INDEX idx_c ON c (id);
    """
    assert _check(src) == []


def test_unprotected_tail_after_commit_is_still_reported() -> None:
    src = """
    BEGIN;
    SET LOCAL lock_timeout = '2s';
    ALTER TABLE a ADD COLUMN x INT;
    COMMIT;
    ALTER TABLE b ADD COLUMN y INT;
    ALTER TABLE c ADD COLUMN z INT;
    """
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 6


def test_a_rollback_drops_the_local_timeout_just_as_a_commit_does() -> None:
    src = """
    BEGIN;
    SET LOCAL lock_timeout = '2s';
    ALTER TABLE a ADD COLUMN x INT;
    ROLLBACK;
    ALTER TABLE b ADD COLUMN y INT;
    """
    diags = _check(src)
    assert len(diags) == 1
    assert diags[0].line == 6


@pytest.mark.parametrize(
    "ddl",
    [
        "ALTER TABLE users ADD COLUMN note TEXT;",
        "CREATE INDEX idx_users_note ON users (note);",
        "CREATE UNIQUE INDEX idx_users_note ON users (note);",
        "DROP TABLE legacy_users;",
    ],
    ids=["alter-table", "create-index", "create-unique-index", "drop-table"],
)
def test_every_ddl_form_needs_a_timeout(ddl: str) -> None:
    assert len(_check(f"{ddl}\n")) == 1
    assert _check(f"SET lock_timeout = '3s';\n{ddl}\n") == []


@pytest.mark.parametrize(
    "ddl",
    [
        "ALTER TYPE status ADD VALUE 'archived';",
        "DROP INDEX idx_users_note;",
        "REINDEX INDEX idx_users_note;",
        "TRUNCATE TABLE audit_log;",
    ],
    ids=["alter-type", "drop-index", "reindex", "truncate"],
)
def test_locking_ddl_forms_need_a_timeout(ddl: str) -> None:
    assert len(_check(f"{ddl}\n")) == 1
    assert _check(f"SET lock_timeout = '3s';\n{ddl}\n") == []


def test_mysql_migration_is_not_asked_for_a_postgres_guc() -> None:
    src = "ALTER TABLE `users` ADD COLUMN `note` TEXT;\n"
    assert _check(src) == []


def test_sqlite_migration_is_not_asked_for_a_postgres_guc() -> None:
    src = "CREATE TABLE `t` (`id` integer PRIMARY KEY AUTOINCREMENT);\nCREATE INDEX `i` ON `t` (`id`);\n"
    assert _check(src) == []


def test_postgres_migration_still_fires_next_to_the_dialect_boundary() -> None:
    src = 'ALTER TABLE "users" ADD COLUMN note TEXT;\n'
    assert len(_check(src)) == 1


def test_set_config_call_counts_as_an_assignment() -> None:
    src = "SELECT set_config('lock_timeout', '5s', false); ALTER TABLE t ADD COLUMN c INT;"
    assert _check(src) == []


def test_transaction_local_set_config_expires_at_commit() -> None:
    source = """
    SELECT set_config('lock_timeout', '5s', true);
    ALTER TABLE a ADD COLUMN x INT;
    COMMIT;
    ALTER TABLE b ADD COLUMN y INT;
    """
    diags = _check(source)
    assert len(diags) == 1
    assert diags[0].line == 5


def test_session_set_config_survives_commit() -> None:
    source = """
    SELECT set_config('lock_timeout', '5s', false);
    ALTER TABLE a ADD COLUMN x INT;
    COMMIT;
    ALTER TABLE b ADD COLUMN y INT;
    """
    assert _check(source) == []


def test_nontransactional_migration_rejects_transaction_local_set_config() -> None:
    source = """
    -- migrate:up transaction:false
    SELECT set_config('lock_timeout', '5s', true);
    ALTER TABLE a ADD COLUMN x INT;
    """
    assert len(_check(source)) == 1


def test_a_schema_dump_is_not_asked_for_a_lock_timeout() -> None:
    src = """
    -- PostgreSQL database dump
    SET statement_timeout = 0;
    SET lock_timeout = 0;
    CREATE TABLE users (id int primary key);
    CREATE INDEX idx_users ON users (id);
    """
    assert _check(src, Path("structure.sql")) == []
    assert _check(src) == []


def test_nontransactional_migration_rejects_ineffective_set_local_timeout() -> None:
    source = """
    -- migrate:up transaction:false
    SET LOCAL lock_timeout = '2s';
    CREATE INDEX CONCURRENTLY idx_users_email ON users(email);
    """

    (finding,) = _check(source)

    assert "session" in finding.message
    assert "SET LOCAL" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        "SELECT '-- migrate:no-transaction';\nSET LOCAL lock_timeout = '2s';\nALTER TABLE t ADD COLUMN c int;",
        "-- documentation mentions -- migrate:no-transaction\nSET LOCAL lock_timeout = '2s';\nALTER TABLE t ADD COLUMN c int;",
        "DO $body$\n-- migrate:no-transaction\n$body$;\nSET LOCAL lock_timeout = '2s';\nALTER TABLE t ADD COLUMN c int;",
    ],
)
def test_nontransactional_mode_requires_an_exact_live_directive(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        Path("queries/create_index.sql"),
        Path("fixtures/migrations/001.sql"),
        Path("mocks/migrations/001.sql"),
        Path("snapshots/migrations/001.sql"),
        Path("clickhouse/migrations/001.sql"),
        Path("d1/migrations/001.sql"),
    ],
    ids=["query", "fixture", "mock", "snapshot", "clickhouse", "d1"],
)
def test_non_production_and_non_postgres_paths_are_out_of_scope(path: Path) -> None:
    assert _check("-- migrate:up\nALTER TABLE users ADD COLUMN note TEXT;", path) == []


def test_ambiguous_plain_migration_is_out_of_scope_without_postgres_evidence() -> None:
    assert _check("ALTER TABLE users ADD COLUMN note TEXT;", Path("db/migrations/001.sql")) == []


def test_extensionless_input_with_migration_directive_stays_in_scope() -> None:
    assert len(_check("-- migrate:up\nALTER TABLE users ADD COLUMN note TEXT;", Path("stdin"))) == 1


@pytest.mark.parametrize(
    "assignment",
    [
        "SET /* deployment */ lock_timeout /* value */ = /* bounded */ '3s';",
        "SET /* deployment\n settings */ LOCAL lock_timeout TO '3s';",
        "SELECT set_config(/* name */ 'lock_timeout', /* value */ '3s', false);",
        "SET lock_timeout = '3s'; -- SET lock_timeout = 0;",
    ],
)
def test_comments_do_not_hide_positive_timeout_assignments(assignment: str) -> None:
    assert _check(f"{assignment}\nALTER TABLE users ADD COLUMN note TEXT;\n") == []


@pytest.mark.parametrize(
    "assignment",
    [
        "/* SET lock_timeout = '3s'; */",
        "SET /* no protection */ lock_timeout = '0s';",
        "SET lock_timeout = '3s'; RESET /* reset */ lock_timeout;",
        "SELECT 'SET lock_timeout = ''3s'';';",
        "SET lock_timeout = '3s'; -- migrate:down\n-- migrate:down",
    ],
)
def test_comment_normalization_retains_unprotected_ddl(assignment: str) -> None:
    assert len(_check(f"{assignment}\nALTER TABLE users ADD COLUMN note TEXT;\n")) == 1


@pytest.mark.parametrize("name", ["lock_timeout", "statement_timeout"])
def test_quoted_timeout_assignment_is_live(name: str) -> None:
    assert _check(f"SET \"{name}\" = '3s'; ALTER TABLE users ADD COLUMN note TEXT;") == []


def test_quoted_timeout_reset_removes_protection() -> None:
    source = 'SET "lock_timeout" = \'3s\'; RESET "lock_timeout"; ALTER TABLE users ADD COLUMN note TEXT;'
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "assignment",
    ["SET \"LOCK_TIMEOUT\" = '3s';", 'SELECT \'SET "lock_timeout" = "3s"\';', 'SELECT "SET lock_timeout = 3s";'],
)
def test_quoted_timeout_decoys_do_not_grant_protection(assignment: str) -> None:
    assert len(_check(assignment + " ALTER TABLE users ADD COLUMN note TEXT;")) == 1


_DBMATE_OPTION_CASES = (
    ("default", "", True),
    ("false", "transaction:false", False),
    ("true", "transaction:true", True),
    ("last-false", "transaction:true transaction:false", False),
    ("last-true", "transaction:false transaction:true", True),
    ("unknown-option", "other:value transaction:false", False),
    ("case-key", "Transaction:false", True),
    ("case-value", "transaction:False", True),
    ("malformed-pair", "transaction:false:extra", True),
)


@pytest.mark.parametrize(
    ("name", "options", "transactional"), _DBMATE_OPTION_CASES, ids=tuple(item[0] for item in _DBMATE_OPTION_CASES)
)
@pytest.mark.parametrize("crlf", [False, True])
def test_dbmate_options_follow_actual_runner_sections(
    name: str, options: str, *, transactional: bool, crlf: bool
) -> None:
    source = f"-- migrate:up {options}\nSET LOCAL lock_timeout = '3s';\nALTER TABLE public_example ADD COLUMN name TEXT;\n-- migrate:down\nALTER TABLE public_example DROP COLUMN name;\n"
    source = source.replace("\n", "\r\n") if crlf else source
    first, second = dbmate_directives(source)
    assert first.transactional is transactional, name
    assert second.transactional
    assert has_dbmate_directive(source, "no-transaction") is (not transactional)
    assert dbmate_transactional(source, source.index("SET LOCAL")) is transactional
    findings = _check(source)
    assert [item.line for item in findings] == ([5] if transactional else [3, 5])


@pytest.mark.parametrize("prefix", ["SELECT 1;\n", "DO $body$\n"])
def test_runner_rejected_prefix_has_no_transaction_context(prefix: str) -> None:
    source = f"{prefix}-- migrate:up transaction:false\nSET LOCAL lock_timeout = '3s';\nALTER TABLE public_example ADD COLUMN name TEXT;\n-- migrate:down\n"
    assert not dbmate_directives(source)
    assert dbmate_transactional(source, source.index("SET LOCAL")) is None


def test_legacy_no_transaction_comment_does_not_override_dbmate() -> None:
    source = "-- migrate:no-transaction\n-- migrate:up\nSET LOCAL lock_timeout = '3s';\nALTER TABLE public_example ADD COLUMN name TEXT;\n-- migrate:down transaction:false\n"
    assert not has_dbmate_directive(source, "no-transaction")
    assert dbmate_transactional(source, source.index("SET LOCAL")) is True
    assert _check(source) == []


def test_mixed_runner_sections_use_each_sections_transaction_options() -> None:
    source = "-- migrate:up transaction:true\nSET LOCAL lock_timeout = '3s';\nALTER TABLE a ADD COLUMN name TEXT;\n-- migrate:down transaction:true\nSET LOCAL lock_timeout = '3s';\nALTER TABLE a DROP COLUMN name;\n-- migrate:up transaction:false\nSET LOCAL lock_timeout = '3s';\nALTER TABLE b ADD COLUMN name TEXT;\n-- migrate:down transaction:true\nSET LOCAL lock_timeout = '3s';\nALTER TABLE b DROP COLUMN name;\n"
    findings = _check(source)
    assert [item.line for item in findings] == [9]
    assert findings == _check(source)


def test_session_timeout_does_not_leak_between_up_sections() -> None:
    source = "-- migrate:up\nSET lock_timeout = '3s';\nALTER TABLE a ADD COLUMN name TEXT;\n-- migrate:up transaction:false\nALTER TABLE b ADD COLUMN name TEXT;\n"
    assert [item.line for item in _check(source)] == [5]


@pytest.mark.parametrize(
    ("prefix", "header", "transactional"),
    [
        ("", "-- migrate:up other:value\u00a0transaction:false", True),
        ("", "-- migrate:up other:value\vtransaction:false", True),
        ("", "--\u00a0migrate:up transaction:false", None),
        ("", "--\vmigrate:up transaction:false", None),
        ("", "--\tmigrate:up other:value\ttransaction:false", False),
        ("\u00a0\n", "-- migrate:up transaction:false", None),
        ("\u00a0-- documentation\n", "-- migrate:up transaction:false", None),
        ("", "-- migrate:up transaction:false\x1c", True),
        ("", "-- migrate:up transaction:false\u00a0", False),
    ],
)
@pytest.mark.parametrize("crlf", [False, True])
def test_dbmate_whitespace_matches_native_runner(
    prefix: str, header: str, transactional: bool | None, *, crlf: bool
) -> None:
    source = f"{prefix}{header}\nSET LOCAL lock_timeout = '3s';\nALTER TABLE public_example ADD COLUMN name TEXT;\n-- migrate:down\n"
    source = source.replace("\n", "\r\n") if crlf else source
    offset = source.index("SET LOCAL")
    assert dbmate_transactional(source, offset) is transactional
    findings = RequireLockTimeout().check(P, source)
    if transactional is None:
        assert all("nontransactional" not in item.message for item in findings)
    else:
        assert [item.line for item in findings] == (
            [source.count("\n", 0, source.index("ALTER TABLE")) + 1] if transactional is False else []
        )
