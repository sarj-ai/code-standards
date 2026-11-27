from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.__main__ import analyze, main
from sarj_sql_lint.autofix import fix_source
from sarj_sql_lint.rules import REGISTRY


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("rule", "sql", "code"),
    [
        ("no-database-functions", "CREATE FUNCTION f() RETURNS int LANGUAGE sql AS $$SELECT 1$$;", "SARJ120"),
        ("no-database-functions", "CREATE PROCEDURE f() LANGUAGE sql AS $$SELECT 1$$;", "SARJ120"),
        ("no-database-functions", "ALTER FUNCTION f() SECURITY DEFINER;", "SARJ120"),
        ("no-database-functions", "ALTER PROCEDURE p() SECURITY DEFINER;", "SARJ120"),
        ("no-database-functions", "ALTER ROUTINE f() IMMUTABLE;", "SARJ120"),
        ("no-database-triggers", "CREATE TRIGGER t BEFORE UPDATE ON work EXECUTE FUNCTION f();", "SARJ114"),
        ("no-database-triggers", "CREATE EVENT TRIGGER t ON ddl_command_start EXECUTE FUNCTION f();", "SARJ114"),
        ("no-database-triggers", "ALTER EVENT TRIGGER t ENABLE ALWAYS;", "SARJ114"),
        ("no-database-triggers", "ALTER TRIGGER t ON work RENAME TO next_t;", "SARJ114"),
        ("no-database-triggers", "ALTER EVENT TRIGGER t OWNER TO app;", "SARJ114"),
        ("no-database-triggers", "ALTER EVENT TRIGGER t RENAME TO next_t;", "SARJ114"),
        ("no-migration-comments", "COMMENT ON TABLE work IS 'work rows';", "SARJ128"),
    ],
)
def test_migration_bans_cannot_be_waived_inline(tmp_path: Path, rule: str, sql: str, code: str) -> None:
    path = tmp_path / "migrations/001_work.sql"
    path.parent.mkdir()
    path.write_text(f"-- dialect: postgres\n{sql} -- sarj-noqa: {code} -- previously approved exception\n")
    findings = analyze([rule], [path])
    assert code in {finding.code for finding in findings}
    assert main(["check", "--rule", rule, str(path)]) == 1


def test_comment_ban_takes_precedence_over_legacy_comment_advice(tmp_path: Path) -> None:
    path = tmp_path / "migrations/001_work.sql"
    path.parent.mkdir()
    path.write_text("-- DROP TABLE work;\n")
    rules = ["no-migration-comments", "no-migration-comment-cruft"]
    findings = analyze(rules, [path])
    assert [(finding.code, finding.line) for finding in findings] == [("SARJ128", 1)]


def test_timeout_requirement_is_retired_and_timeout_free_migration_passes(tmp_path: Path) -> None:
    path = tmp_path / "migrations/001_work.sql"
    path.parent.mkdir()
    path.write_text(
        "-- migrate:up\nCREATE TABLE IF NOT EXISTS work (id UUID PRIMARY KEY);\n"
        "-- migrate:down\nDROP TABLE IF EXISTS work;\n"
    )
    assert "require-lock-timeout" not in REGISTRY
    assert analyze(list(REGISTRY), [path]) == []


@pytest.mark.parametrize(
    "statement",
    [
        "SET LOCAL lock_timeout = '5s';",
        "SET statement_timeout = '60s';",
        "RESET lock_timeout;",
        "RESET statement_timeout;",
    ],
)
def test_timeout_settings_need_no_comment_and_are_preserved(tmp_path: Path, statement: str) -> None:
    path = tmp_path / "migrations/001_timeout.sql"
    path.parent.mkdir()
    path.write_text(statement + "\n")
    assert "migration-timeout-requires-justification" not in REGISTRY
    assert analyze(list(REGISTRY), [path]) == []
    assert fix_source(path, path.read_text(), rule_ids=list(REGISTRY)) == path.read_text()


def test_existing_timeout_directives_remain_compatible(tmp_path: Path) -> None:
    path = tmp_path / "migrations/001_timeout.sql"
    path.parent.mkdir()
    source = "-- timeout-justification: lock_timeout -- bounded operation\nSET LOCAL lock_timeout = '5s';\n"
    path.write_text(source)
    assert analyze(list(REGISTRY), [path]) == []
    assert fix_source(path, source, rule_ids=list(REGISTRY)) == source
