from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_sql_lint.__main__ import analyze
from sarj_sql_lint.autofix import fix_source
from sarj_sql_lint.rule_base import DefaultLevel, is_dump_file, is_explicit_dump_file
from sarj_sql_lint.rules._migration_timeouts import migration_timeout_controls
from sarj_sql_lint.rules.migration_timeout_requires_justification import MigrationTimeoutRequiresJustification
from sarj_sql_lint.rules.no_migration_comments import NoMigrationComments


_PATH = Path("migrations/001_timeout.sql")
_SETTINGS = (
    "statement_timeout",
    "lock_timeout",
    "idle_in_transaction_session_timeout",
    "idle_session_timeout",
    "transaction_timeout",
    "deadlock_timeout",
)


def _check(source: str, path: Path = _PATH):
    return MigrationTimeoutRequiresJustification().check(path, source)


def _reason(setting: str, statement: str) -> str:
    return f"-- timeout-justification: {setting} -- bounded backfill needs this session override\n{statement}\n"


def test_documented_examples() -> None:
    verify_native_rule(MigrationTimeoutRequiresJustification, analyze)


@pytest.mark.parametrize("setting", _SETTINGS, ids=_SETTINGS)
@pytest.mark.parametrize("scope", ["", "LOCAL ", "SESSION "], ids=["plain", "transaction", "session"])
@pytest.mark.parametrize("operator", ["= '5min'", "TO DEFAULT", "FROM CURRENT"], ids=["literal", "default", "current"])
def test_all_timeout_set_forms_require_a_reason(setting: str, scope: str, operator: str) -> None:
    source = f"SET {scope}{setting} {operator};\n"
    [finding] = _check(source)
    assert finding.code == "SARJ131"
    assert finding.severity is DefaultLevel.ERROR
    assert (finding.line, finding.col) == (1, 1)
    assert setting in finding.message
    assert _check(_reason(setting, source)) == []


@pytest.mark.parametrize("setting", _SETTINGS, ids=_SETTINGS)
def test_reset_requires_its_own_reason(setting: str) -> None:
    source = f"RESET {setting};"
    assert len(_check(source)) == 1
    assert _check(_reason(setting, source)) == []


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
def test_case_quotes_multiline_and_physical_locations(ending: str) -> None:
    source = "\n\tSeT\n LOCAL\n \"STATEMENT_TIMEOUT\"\n TO '5min';\n"
    [finding] = _check(source.replace("\n", ending))
    assert (finding.line, finding.col) == (2, 2)
    justified = f"-- TIMEOUT-JUSTIFICATION: STATEMENT_TIMEOUT -- bounded operation needs this deadline\n{source[1:]}"
    assert _check(justified.replace("\n", ending)) == []


def test_zero_headers_cannot_exempt_themselves_as_a_dump() -> None:
    source = "SET statement_timeout = 0;\nSET lock_timeout = 0;\n"
    assert is_dump_file(source, _PATH)
    assert not is_explicit_dump_file(source, _PATH)
    assert [finding.line for finding in _check(source)] == [1, 2]


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("SET search_path = public; RESET work_mem;", id="unrelated-settings"),
        pytest.param("SET application.statement_timeout = '5s';", id="custom-qualified-setting"),
        pytest.param("SET \"application.statement_timeout\" = '5s';", id="custom-quoted-setting"),
        pytest.param("SET statement_timeout_ms = 5;", id="name-prefix"),
        pytest.param("ALTER ROLE reader SET statement_timeout = '5s';", id="role-policy"),
        pytest.param("ALTER DATABASE app SET lock_timeout = '5s';", id="database-policy"),
        pytest.param("SELECT set_config('statement_timeout', '0', false);", id="dynamic-call-outside-contract"),
        pytest.param("RESET ALL;", id="global-reset-outside-contract"),
        pytest.param("SELECT 'SET statement_timeout = 0;';", id="scalar-string"),
        pytest.param("SELECT $sql$SET lock_timeout = 0;$sql$;", id="scalar-dollar"),
        pytest.param('SELECT "SET statement_timeout = 0;";', id="quoted-identifier"),
        pytest.param("-- SET statement_timeout = 0;\nSELECT 1;", id="line-comment"),
        pytest.param("/* nested /* SET lock_timeout = 0; */ */ SELECT 1;", id="nested-block-comment"),
        pytest.param("DO $$ BEGIN SET LOCAL statement_timeout = 0; END $$;", id="procedural-dollar-body"),
        pytest.param(
            "CREATE FUNCTION f() RETURNS void LANGUAGE sql AS 'SET statement_timeout = 0;';", id="string-function-body"
        ),
        pytest.param(
            "CREATE FUNCTION f() RETURNS void LANGUAGE sql BEGIN ATOMIC SET statement_timeout = 0; END;",
            id="standard-function-body-abstains",
        ),
        pytest.param("COPY sample FROM STDIN;\nSET statement_timeout = 0;\n\\.\n", id="copy-payload"),
        pytest.param('SET "unterminated = 0;', id="malformed-identifier-abstains"),
        pytest.param("-- dialect: sqlite\nSET statement_timeout = 0;", id="declared-other-dialect"),
    ],
)
def test_appropriate_or_unsupported_representations_are_not_timeout_headers(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "prefix",
    [
        pytest.param("-- timeout-justification: statement_timeout --\n", id="empty-reason"),
        pytest.param("-- timeout-justification: statement_timeout -- !!!\n", id="punctuation-only"),
        pytest.param("-- timeout-justification: lock_timeout -- bounded backfill\n", id="different-setting"),
        pytest.param("-- timeout-justification: statement_timeout -- bounded backfill\n\n", id="blank-line-gap"),
        pytest.param("/* timeout-justification: statement_timeout -- bounded backfill */\n", id="block-comment"),
        pytest.param("-- bounded backfill needs this deadline\n", id="ordinary-comment"),
        pytest.param(
            "-- timeout-justification: statement_timeout -- bounded backfill\nSELECT 1;\n", id="intervening-statement"
        ),
        pytest.param(
            "SELECT $sql$\n-- timeout-justification: statement_timeout -- bounded backfill\n$sql$;\n",
            id="dollar-data-reason",
        ),
        pytest.param(
            "DO $$\n-- timeout-justification: statement_timeout -- bounded backfill\n$$;\n", id="procedural-reason"
        ),
    ],
)
def test_malformed_or_unbound_reasons_do_not_waive_a_statement(prefix: str) -> None:
    assert len(_check(f"{prefix}SET statement_timeout = '5min';")) == 1


def test_one_directive_does_not_waive_another_control_on_the_same_line() -> None:
    statement = "SET statement_timeout = '5min'; RESET statement_timeout;"
    source = _reason("statement_timeout", statement)
    [finding] = _check(source)
    assert (finding.line, finding.col) == (2, statement.index("RESET") + 1)


def test_same_line_quoted_semicolon_does_not_move_statement_boundaries() -> None:
    source = "SELECT \"a;SET statement_timeout\"; SET lock_timeout = '1s;RESET statement_timeout';"
    [finding] = _check(source)
    assert (finding.line, finding.col) == (1, source.index("SET lock_timeout") + 1)


def test_bom_and_unicode_reason_keep_locations() -> None:
    [finding] = _check("\ufeffSET lock_timeout = 0;")
    assert (finding.line, finding.col) == (1, 2)
    source = "\ufeff-- timeout-justification: lock_timeout -- délai nécessaire pour le backfill\nSET lock_timeout = 0;"
    assert _check(source) == []


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(Path("schema.sql"), id="schema-snapshot"),
        pytest.param(Path("migrations/archive_dump.sql"), id="named-dump"),
        pytest.param(Path("restore/migrations/001.sql"), id="restore-tree"),
        pytest.param(Path("queries/migrations/001.sql"), id="queries"),
        pytest.param(Path("tests/migrations/001.sql"), id="test-migration"),
        pytest.param(Path("scripts/setup.sql"), id="operational-script"),
    ],
)
def test_non_migration_and_snapshot_boundaries(path: Path) -> None:
    assert _check("SET statement_timeout = 0;", path) == []


def test_explicit_dump_header_is_preserved_but_string_data_is_not_a_dump() -> None:
    assert _check("-- PostgreSQL database dump\nSET lock_timeout = 0;") == []
    assert len(_check("SELECT 'PostgreSQL database dump'; SET lock_timeout = 0;")) == 1


def test_generator_owned_source_is_left_to_its_model(tmp_path: Path) -> None:
    (tmp_path / "migration_lock.toml").write_text('provider = "postgresql"\n')
    path = tmp_path / "migrations/001.sql"
    path.parent.mkdir()
    path.write_text("SET statement_timeout = 0;")
    assert _check(path.read_text(), path) == []


@pytest.mark.parametrize("suffix", ["", " -- unreviewed waiver"], ids=["bare", "reasoned-generic-waiver"])
def test_generic_noqa_does_not_bypass_the_reason_contract(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / "migrations/001.sql"
    path.parent.mkdir()
    path.write_text(f"SET lock_timeout = 0; -- sarj-noqa: SARJ131{suffix}\n")
    [finding] = analyze([MigrationTimeoutRequiresJustification.id], [path])
    assert finding.code == "SARJ131"


def test_valid_directive_coexists_with_comment_enforcement_and_cache_mutation(tmp_path: Path) -> None:
    path = tmp_path / "migrations/001.sql"
    path.parent.mkdir()
    source = _reason("lock_timeout", "SET LOCAL lock_timeout = '3s';")
    path.write_text(source)
    selected = [MigrationTimeoutRequiresJustification.id, NoMigrationComments.id]
    assert analyze(selected, [path]) == []
    assert fix_source(path, source, rule_ids=selected) == source
    path.write_text(source.replace("lock_timeout --", "statement_timeout --"))
    findings = analyze(selected, [path])
    assert [(finding.code, finding.line) for finding in findings] == [("SARJ131", 2), ("SARJ128", 1)]
    assert len({(finding.code, finding.line, finding.col) for finding in findings}) == len(findings)


def test_orphan_directive_is_not_a_comment_exemption() -> None:
    source = "-- timeout-justification: lock_timeout -- bounded operation\nSELECT 1;\n"
    [finding] = NoMigrationComments().check(_PATH, source)
    assert finding.code == "SARJ128"
    assert finding.line == 1


def test_policy_does_not_offer_a_timeout_deletion_fix() -> None:
    source = "SET statement_timeout = '10min';\nRESET statement_timeout;\n"
    assert fix_source(_PATH, source, rule_ids=[MigrationTimeoutRequiresJustification.id]) == source
    assert len(migration_timeout_controls(source)) == 2
