from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_sql_lint.__main__ import analyze
from sarj_sql_lint.rules.invalid_concurrent_ddl import InvalidConcurrentDdl


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic


_PATH = Path("migrations/001_change.sql")
_CREATE = "CREATE INDEX CONCURRENTLY account_email ON account(email);"
_DROP = "DROP INDEX CONCURRENTLY IF EXISTS account_email;"


def _check(source: str) -> list[Diagnostic]:
    return InvalidConcurrentDdl().check(_PATH, source)


def test_documented_examples() -> None:
    verify_native_rule(InvalidConcurrentDdl, analyze)


@pytest.mark.parametrize("command", [_CREATE, _DROP])
@pytest.mark.parametrize(
    "begin",
    [
        "BEGIN;",
        "begin work;",
        "BEGIN TRANSACTION;",
        "START TRANSACTION;",
        "BEGIN ISOLATION LEVEL REPEATABLE READ, READ ONLY;",
        "START TRANSACTION ISOLATION LEVEL SERIALIZABLE READ WRITE NOT DEFERRABLE;",
    ],
)
def test_concurrent_index_commands_reject_proved_transactions(begin: str, command: str) -> None:
    (finding,) = _check(f"{begin}\n{command}\nCOMMIT;")
    assert "inside a transaction block" in finding.message


@pytest.mark.parametrize("command", [_CREATE, _DROP])
@pytest.mark.parametrize("end", ["COMMIT", "END WORK", "ROLLBACK", "ABORT TRANSACTION", "COMMIT AND NO CHAIN"])
def test_transaction_end_releases_the_block(end: str, command: str) -> None:
    assert _check(f"BEGIN; {end}; {command}") == []


@pytest.mark.parametrize(
    "end", ["COMMIT AND CHAIN", "END TRANSACTION AND CHAIN", "ROLLBACK AND CHAIN", "ABORT AND CHAIN"]
)
def test_chained_transactions_keep_the_block(end: str) -> None:
    assert len(_check(f"BEGIN; {end}; {_CREATE}")) == 1


def test_chain_without_a_proven_prior_transaction_does_not_invent_one() -> None:
    assert _check(f"COMMIT AND CHAIN; {_CREATE}") == []


@pytest.mark.parametrize(
    "rollback", ["ROLLBACK TO point", "ROLLBACK TO SAVEPOINT point", 'ROLLBACK WORK TO SAVEPOINT "a;b"']
)
def test_savepoint_rollback_does_not_end_the_transaction(rollback: str) -> None:
    assert len(_check(f"BEGIN; SAVEPOINT point; {rollback}; {_CREATE}")) == 1


def test_preparing_the_transaction_ends_the_block() -> None:
    assert _check(f"BEGIN; PREPARE TRANSACTION 'prepared'; {_CREATE}") == []


@pytest.mark.parametrize("command", [_CREATE, _DROP])
def test_valid_dbmate_directive_proves_a_transaction(command: str) -> None:
    assert len(_check(f"-- migrate:up\n{command}")) == 1


@pytest.mark.parametrize("command", [_CREATE, _DROP])
def test_dbmate_nontransactional_section_does_not_invent_a_transaction(command: str) -> None:
    assert _check(f"-- migrate:up transaction:false\n{command}") == []


def test_explicit_begin_inside_nontransactional_runner_is_still_a_transaction() -> None:
    assert len(_check(f"-- migrate:up transaction:false\nBEGIN; {_CREATE}")) == 1


def test_explicit_commit_ends_the_runner_transaction_proof() -> None:
    assert _check(f"-- migrate:up\nCOMMIT; {_CREATE}") == []


def test_dbmate_up_down_sections_reset_transaction_state() -> None:
    source = f"-- migrate:up transaction:false\n{_CREATE}\n-- migrate:down\n{_DROP}\n"
    (finding,) = _check(source)
    assert finding.line == 4


def test_dbmate_nontransactional_down_resets_explicit_up_transaction() -> None:
    source = f"-- migrate:up transaction:false\nBEGIN; SELECT 1;\n-- migrate:down transaction:false\n{_DROP}\n"
    assert _check(source) == []


@pytest.mark.parametrize(
    "source",
    [
        f"-- prose mentions -- migrate:up\n{_CREATE}",
        f"SELECT '-- migrate:up';\n{_CREATE}",
        f"/* -- migrate:up */\n{_CREATE}",
        f"-- +goose Up\n{_CREATE}",
        f"SELECT 'BEGIN;'; {_CREATE}",
        f'SELECT "BEGIN;"; {_CREATE}',
        f"-- BEGIN;\n{_CREATE}",
        f"/* BEGIN; */ {_CREATE}",
        f"SELECT $data$BEGIN; COMMIT AND CHAIN;$data$; {_CREATE}",
        f"DO $$ BEGIN PERFORM 1; END $$; {_CREATE}",
    ],
)
def test_data_comments_and_unknown_runner_contexts_do_not_prove_transactions(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    ("targets", "expected"),
    [
        ("first_idx, second_idx", 1),
        ('"first,idx"', 0),
        ('"first;idx"', 0),
        ('"a""b,c"', 0),
        ('public."a,b", private."x;y"', 1),
        ("public.नाम, other.नाम", 1),
        ('"CASCADE"', 0),
    ],
)
def test_concurrent_drop_counts_real_targets(targets: str, expected: int) -> None:
    assert len(_check(f"DROP INDEX CONCURRENTLY IF EXISTS {targets};")) == expected


@pytest.mark.parametrize("option", ["CASCADE", "cascade", "/* local note */ CASCADE"])
def test_concurrent_drop_forbids_cascade(option: str) -> None:
    (finding,) = _check(f"DROP INDEX CONCURRENTLY account_email {option};")
    assert "does not support `CASCADE`" in finding.message


def test_multiple_restrictions_share_one_command_diagnostic() -> None:
    (finding,) = _check("BEGIN; DROP INDEX CONCURRENTLY first_idx, second_idx CASCADE;")
    assert "transaction block" in finding.message
    assert "one index" in finding.message
    assert "CASCADE" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        "BEGIN; CREATE INDEX account_email ON account(email); COMMIT;",
        "BEGIN; DROP INDEX first_idx, second_idx CASCADE; COMMIT;",
        "DROP INDEX CONCURRENTLY account_email RESTRICT;",
        "REFRESH MATERIALIZED VIEW summary WITH NO DATA;",
        "REFRESH MATERIALIZED VIEW CONCURRENTLY summary WITH DATA;",
        "REFRESH MATERIALIZED VIEW CONCURRENTLY summary;",
        'REFRESH MATERIALIZED VIEW CONCURRENTLY "WITH NO DATA";',
        'DROP INDEX CONCURRENTLY "CASCADE";',
        "BEGIN ATOMIC; CREATE INDEX CONCURRENTLY account_email ON account(email);",
    ],
)
def test_compatible_or_unproved_command_forms_remain_valid(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("relation", ["summary", "public.summary", '"WITH NO DATA"', '"a;b"', "public.नाम"])
def test_concurrent_refresh_cannot_request_no_data(relation: str) -> None:
    (finding,) = _check(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {relation} WITH NO DATA;")
    assert "cannot be combined" in finding.message


@pytest.mark.parametrize(
    "source",
    [
        "DROP INDEX CONCURRENTLY;",
        "DROP INDEX CONCURRENTLY first_idx,;",
        "DROP INDEX CONCURRENTLY first_idx extra CASCADE;",
        "DROP INDEX CONCURRENTLY first_idx 'CASCADE';",
        "REFRESH MATERIALIZED VIEW CONCURRENTLY WITH NO DATA;",
        "REFRESH MATERIALIZED VIEW CONCURRENTLY summary WITH NO DATA unexpected;",
        "BEGIN; CREATE INDEX CONCURRENTLY;",
        "BEGIN; CREATE INDEX CONCURRENTLY i ON;",
    ],
)
def test_incomplete_or_unsupported_commands_abstain(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize("line_ending", ["\n", "\r\n", "\r"])
def test_locations_preserve_physical_lines_and_same_line_offsets(line_ending: str) -> None:
    source = f"BEGIN;{line_ending}  SELECT 1; {_CREATE}{line_ending}"
    (finding,) = _check(source)
    assert (finding.line, finding.col) == (2, 13)


@pytest.mark.parametrize(
    "path",
    [
        "tests/migrations/001.sql",
        "fixtures/migrations/001.sql",
        "migrations/schema.sql",
        "migrations/structure.sql",
        "queries/index.sql",
        "mysql/migrations/001.sql",
        "sqlite/migrations/001.sql",
    ],
)
def test_nonproduction_dumps_and_nonmigration_sources_are_excluded(path: str) -> None:
    assert InvalidConcurrentDdl().check(Path(path), f"BEGIN; {_CREATE}") == []


def test_declared_other_dialect_is_excluded() -> None:
    assert _check(f"-- dialect: sqlite\nBEGIN; {_CREATE}") == []


def test_generated_migration_is_excluded() -> None:
    assert _check(f"BEGIN;\n--> statement-breakpoint\n{_CREATE}") == []


def test_real_cli_suppression_only_waives_its_command(tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    directory.mkdir()
    path = directory / "001_index.sql"
    path.write_text(f"BEGIN;\n{_CREATE} -- sarj-noqa: SARJ125 -- documented fixture\n{_DROP}\n", encoding="utf-8")
    (finding,) = analyze([InvalidConcurrentDdl.id], [path])
    assert finding.line == 3
    assert finding.code == "SARJ125"


def test_sql_standard_routine_bodies_do_not_create_top_level_transaction_proof() -> None:
    source = (
        "BEGIN; CREATE PROCEDURE example() LANGUAGE SQL BEGIN ATOMIC "
        "SELECT 1; CREATE INDEX CONCURRENTLY i ON account(email); END; COMMIT;"
    )
    assert _check(source) == []


def test_many_dollar_literals_keep_linear_masking_and_original_ddl_location() -> None:
    values = "SELECT $value$; CONCURRENTLY /* data */$value$;\n" * 3000
    source = values + "BEGIN;\nDROP INDEX CONCURRENTLY a, b CASCADE;"
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].line == 3002
    assert "transaction block" in findings[0].message


@pytest.mark.parametrize(
    "command",
    [
        "CREATE INDEX CONCURRENTLY i ON account;",
        "CREATE INDEX CONCURRENTLY ON account;",
        "CREATE INDEX CONCURRENTLY i ON account();",
        "CREATE INDEX CONCURRENTLY i ON account( );",
        "CREATE INDEX CONCURRENTLY i ON account INCLUDE (email);",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ON account(email);",
    ],
)
def test_incomplete_index_definitions_abstain(command: str) -> None:
    assert _check(f"BEGIN; {command}") == []


@pytest.mark.parametrize(
    "command",
    [
        "CREATE INDEX CONCURRENTLY ON account(email);",
        "CREATE INDEX CONCURRENTLY i ON account ((lower(email)));",
        "CREATE INDEX CONCURRENTLY i ON account(email) WHERE email IS NOT NULL;",
        "CREATE INDEX CONCURRENTLY i ON account(email) INCLUDE (id);",
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS i ON account(email);",
        "CREATE INDEX CONCURRENTLY i ON account(email) WITH (fillfactor = 70);",
    ],
)
def test_complete_index_definitions_keep_transaction_findings(command: str) -> None:
    (finding,) = _check(f"BEGIN; {command}")
    assert "inside a transaction block" in finding.message
    assert _check(command) == []


@pytest.mark.parametrize(
    "copy",
    [
        "COPY seed(text) FROM STDIN;",
        'COPY public."seed;data" (text) FROM stdin;',
        "COPY seed FROM STDIN WITH (FORMAT csv);",
    ],
)
def test_copy_input_is_not_executable_ddl(copy: str) -> None:
    source = f"{copy}\nrow;\nDROP INDEX CONCURRENTLY a, b CASCADE;\n\\.\n"
    assert _check(source) == []


def test_copy_input_cannot_create_transaction_proof_for_later_commands() -> None:
    source = f"COPY seed(text) FROM STDIN;\nrow;\nBEGIN;\n\\.\nSELECT 1;\n{_CREATE}"
    assert _check(source) == []


def test_copy_native_boundary_preserves_earlier_findings() -> None:
    source = "DROP INDEX CONCURRENTLY a, b;\nCOPY seed FROM STDIN;\nrow;\nDROP INDEX CONCURRENTLY x, y;\n\\.\n"
    (finding,) = _check(source)
    assert (finding.line, finding.col) == (1, 1)
    assert "one index" in finding.message


@pytest.mark.parametrize(
    "command",
    [
        "COPY seed TO STDOUT;",
        "COPY seed FROM 'STDIN';",
        "COPY seed FROM PROGRAM 'STDIN';",
        "SELECT 'COPY seed FROM STDIN';",
        "DO $$ BEGIN PERFORM 'COPY seed FROM STDIN'; END $$;",
    ],
)
def test_copy_near_misses_do_not_end_analysis(command: str) -> None:
    (finding,) = _check(f"{command}\nBEGIN; {_CREATE}")
    assert finding.line == 2
    assert "inside a transaction block" in finding.message
