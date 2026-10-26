from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlglot import exp

from sarj_sql_lint.__main__ import main
from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.autofix import fix_source
from sarj_sql_lint.rules.excessive_commentary import ExcessiveCommentary


if TYPE_CHECKING:
    from sarj_rule_contracts import RuleId


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("CREATE TABLE users (id INT);\n", "CREATE TABLE IF NOT EXISTS users (id INT);\n"),
        ("CREATE INDEX CONCURRENTLY ix ON users(id);", "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix ON users(id);"),
        ("DROP INDEX CONCURRENTLY ix;", "DROP INDEX CONCURRENTLY IF EXISTS ix;"),
        ("ALTER TABLE users ADD COLUMN email TEXT;", "ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;"),
        ("-- ==== Users ====\r\nSELECT '☃';\r\n", "\r\nSELECT '☃';\r\n"),
        ("-- DROP TABLE legacy;\nSELECT 1;\n", "\nSELECT 1;\n"),
        ("-- CREATE TABLE old (\n-- id INT\n-- );\nSELECT 1;\n", "\n\n\nSELECT 1;\n"),
    ],
)
def test_safe_fixes_parse_and_converge(source: str, expected: str) -> None:
    path = Path("migrations/001.sql")
    fixed = fix_source(path, source)
    assert fixed == expected
    assert parse_postgres(fixed)
    assert fix_source(path, fixed) == fixed


@pytest.mark.parametrize(
    "source",
    [
        "CREATE TABLE users (id INT); -- sarj-noqa: SARJ102\n",
        "--> statement-breakpoint\nCREATE TABLE users (id INT);\n",
        "CREATE TABLE users (id INT;\n",
        "-- TODO: recover the old table\nSELECT 1;\n",
        "-- ==== License ====\nSELECT 1;\n",
        "-- ==== sqlfluff ====\nSELECT 1;\n",
        "-- Rollback: DROP TABLE users;\nSELECT 1;\n",
        "-- Reference OPS-812\n-- DROP TABLE users;\nSELECT 1;\n",
        "SELECT $$-- DROP TABLE users;$$;\n",
        "CREATE TABLE users (id INT);\n-- dialect: mysql\n",
    ],
)
def test_uncertain_or_owned_sql_is_preserved(source: str) -> None:
    assert fix_source(Path("migrations/001.sql"), source) == source


def test_disabled_rule_does_not_fix() -> None:
    source = "CREATE TABLE users (id INT);\n"
    assert fix_source(Path("migrations/001.sql"), source, rule_ids=[]) == source


def test_type_and_runtime_policy_are_preserved() -> None:
    source = "CREATE TABLE IF NOT EXISTS users (id UUID DEFAULT uuidv7(), at TIMESTAMP, v VARCHAR(5), j JSON);"
    assert fix_source(Path("migrations/001.sql"), source) == source


def test_cli_fix_preserves_crlf_and_permissions(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "migration.sql"
    path.write_bytes(b"CREATE TABLE users (id INT);\r\n")
    path.chmod(0o755)
    assert main(["check", "--rule", "idempotent-ddl", "--fix", str(path)]) == 0
    assert path.read_bytes() == b"CREATE TABLE IF NOT EXISTS users (id INT);\r\n"
    assert path.stat().st_mode & 0o777 == 0o755
    assert not capsys.readouterr().out


@pytest.mark.parametrize(
    ("rule_id", "source", "exit_code"),
    [
        ("idempotent-ddl", "CREATE TABLE users (id INT); -- sarj-noqa: SARJ102\n", 0),
        ("idempotent-ddl", "CREATE TABLE users (id INT;\n", 1),
        ("enforce-timestamptz", "CREATE TABLE users (id INT);\n", 0),
    ],
)
def test_cli_fix_respects_suppression_selection_and_malformed_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], rule_id: RuleId, source: str, exit_code: int
) -> None:
    path = tmp_path / "migration.sql"
    path.write_bytes(source.encode())
    assert main(["check", "--rule", rule_id, "--fix", str(path)]) == exit_code
    assert path.read_bytes() == source.encode()
    capsys.readouterr()


def test_cli_fix_refuses_symlink(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "migration.sql"
    source = b"CREATE TABLE users (id INT);\n"
    path.write_bytes(source)
    link = tmp_path / "linked.sql"
    link.symlink_to(path)
    assert main(["check", "--rule", "idempotent-ddl", "--fix", str(link)]) == 2
    assert path.read_bytes() == source
    assert link.is_symlink()
    assert "symlink" in capsys.readouterr().err


@pytest.mark.parametrize(
    "rule_ids",
    [
        ["no-long-migration-narration"],
        ["no-long-migration-narration", "no-migration-comment-cruft"],
        ["no-migration-comment-cruft", "no-long-migration-narration"],
    ],
)
def test_disabled_sql_narration_is_fixable_when_selected_alone_or_together(rule_ids: list[RuleId]) -> None:
    path = Path("migrations/001.sql")
    source = "".join(
        f"-- CREATE TABLE {name} (id BIGINT PRIMARY KEY, name TEXT);\n"
        for name in ("users", "groups", "teams", "accounts")
    )
    assert len(ExcessiveCommentary().check(path, source)) == 1
    fixed = fix_source(path, source, rule_ids=rule_ids)
    assert fixed == "\n\n\n\n"
    assert fix_source(path, fixed, rule_ids=rule_ids) == fixed
    assert fix_source(path, source, rule_ids=[]) == source
    suppressed = source.replace(";\n", "; -- sarj-noqa: SARJ115\n", 1)
    assert fix_source(path, suppressed, rule_ids=["no-long-migration-narration"]) == suppressed


@pytest.mark.parametrize(
    "source",
    [
        "-- ==== Old ====\n-- ==== Unused ====\nSELECT 1;\n",
        "-- ==== Old ====\n-- DROP TABLE old;\nSELECT 1;\n",
    ],
)
def test_banner_and_disabled_code_groups_converge_in_one_application(source: str) -> None:
    path = Path("migrations/001.sql")
    fixed = fix_source(path, source)
    assert fixed == "\n\nSELECT 1;\n"
    assert fix_source(path, fixed) == fixed


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "SELECT '\n-- ========\n-- ' AS sample;\n-- ========\nSELECT 1;\n",
            "SELECT '\n-- ========\n-- ' AS sample;\n\nSELECT 1;\n",
        ),
        (
            "SELECT $payload$\n-- ========\n-- $payload$ AS sample;\n-- ========\nSELECT 1;\n",
            "SELECT $payload$\n-- ========\n-- $payload$ AS sample;\n\nSELECT 1;\n",
        ),
        (
            "/*\n-- ========\n-- */\n-- ========\nSELECT 1;\n",
            "/*\n-- ========\n-- */\n\nSELECT 1;\n",
        ),
    ],
)
def test_comment_groups_preserve_adjacent_literal_and_block_regions(source: str, expected: str) -> None:
    path = Path("migrations/001.sql")
    fixed = fix_source(path, source, rule_ids=["no-migration-comment-cruft"])
    assert fixed == expected
    before = [literal.text("this") for tree in parse_postgres(source) if tree for literal in tree.find_all(exp.Literal)]
    after = [literal.text("this") for tree in parse_postgres(fixed) if tree for literal in tree.find_all(exp.Literal)]
    assert before == after
    assert fix_source(path, fixed, rule_ids=["no-migration-comment-cruft"]) == fixed
