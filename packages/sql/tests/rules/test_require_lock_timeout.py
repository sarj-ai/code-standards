"""SARJ110 — the assignment-spelling parser fix, per-state collapse, and dialect guard."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.require_lock_timeout import RequireLockTimeout


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


P = Path("supabase/migrations/001_schema.sql")


def _check(source: str, path: Path = P) -> list[Diagnostic]:
    return RequireLockTimeout().check(path, source)


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
    """The boundary: the spelling parses, but `0` means "wait forever"."""
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
    """`SET lock_timeout = 'abc'` is a runtime error, not a shorter lock wait."""
    assert len(_check(f"SET lock_timeout = {value};\nALTER TABLE t ADD COLUMN c INT;\n")) == 1


@pytest.mark.parametrize("value", ["'3s'", "'250ms'", "'1min'", "5000", "'2.5s'"])
def test_a_plausible_interval_is_protection(value: str) -> None:
    """The boundary: the check must reject prose without rejecting real intervals."""
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
    r"""`\b` after the name: `lock_timeout_ms` is a different GUC."""
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
    """The boundary: collapsing must not swallow a *second* unprotected region."""
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
    """`ROLLBACK` ends the transaction too — `SET LOCAL` does not survive it."""
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
    """`DROP TABLE` takes ACCESS EXCLUSIVE like the rest and can queue behind a reader."""
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
    """The boundary: same DDL, no dialect marker — the guard must not widen to this."""
    src = 'ALTER TABLE "users" ADD COLUMN note TEXT;\n'
    assert len(_check(src)) == 1


def test_set_config_call_counts_as_an_assignment() -> None:
    """`set_config(...)` is the function spelling of `SET`, and protects just as well."""
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
    -- migrate:no-transaction
    SELECT set_config('lock_timeout', '5s', true);
    ALTER TABLE a ADD COLUMN x INT;
    """
    assert len(_check(source)) == 1


def test_a_schema_dump_is_not_asked_for_a_lock_timeout() -> None:
    """A dump replays a whole database offline; there is no concurrent traffic to lock out."""
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
    -- migrate:no-transaction
    -- migrate:up
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
