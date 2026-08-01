"""SARJ110 — the assignment-spelling parser fix, per-state collapse, and dialect guard."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.require_lock_timeout import RequireLockTimeout


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


P = Path("migration.sql")


def _check(source: str, path: Path = P) -> list[Diagnostic]:
    return RequireLockTimeout().check(path, source)


# --- the parser bug: every spelling of the assignment must be recognised ---------
#
# The rule previously required TWO runs of whitespace after `SET` whenever the
# optional LOCAL/SESSION keyword was absent, so the ordinary single-space form was
# invisible and the migration below — which already complies — was reported.


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


def test_zero_timeout_is_not_protection() -> None:
    """The boundary: the spelling parses, but `0` means "wait forever"."""
    assert len(_check("SET lock_timeout = 0;\nALTER TABLE users ADD COLUMN note TEXT;\n")) == 1


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
    """The liveness check: the pattern runs on raw source, so the *position* must be live.

    `ASSIGNMENT_PATTERN` is deliberately matched against unmasked source — a
    timeout value is a `'3s'` string literal and the masker would blank it away.
    The price is that prose matches too, so every match is re-checked against
    `mask_sql` output at its own offset. Without that check a migration is
    "protected" by a commented-out line someone left behind.
    """
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


def test_similarly_named_setting_is_not_lock_timeout() -> None:
    r"""`\b` after the name: `lock_timeout_ms` is a different GUC."""
    assert len(_check("SET lock_timeout_ms = '3s';\nALTER TABLE t ADD COLUMN c INT;\n")) == 1


# --- session state is a property of the file, not of each statement --------------


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


# --- dialect ---------------------------------------------------------------------


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


# --- assignment forms the regex cannot see, and the dump exemption ----------------


def test_set_config_call_counts_as_an_assignment() -> None:
    """`set_config(...)` is the function spelling of `SET`, and protects just as well."""
    src = "SELECT set_config('lock_timeout', '5s', false); ALTER TABLE t ADD COLUMN c INT;"
    assert _check(src) == []


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
