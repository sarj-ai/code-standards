from pathlib import Path

import pytest
from sarj_rule_contracts import RuleId

from sarj_sql_lint.__main__ import main
from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.autofix import fix_source
from sarj_sql_lint.rules.declared_column_bounds import DeclaredColumnBounds
from sarj_sql_lint.rules.no_migration_comments import NoMigrationComments


MIGRATION = Path("migrations/001.sql")


@pytest.mark.parametrize(
    "source",
    [
        "-- Enforced in the application, between 1 and 10.\nSELECT 1;",
        "CREATE TABLE settings (n INTEGER); -- required; capped 1..10",
        "/* Keep this invariant intact. */ SELECT 1;",
        "/* outer /* nested */ comment */ SELECT 1;",
        "SELECT 1; -- sarj-noqa: SARJ128",
        "SELECT 1; -- sarj-noqa",
        "-- sarj-migration-atomicity: lock=bounded\nSELECT 1;",
        "COMMENT ON COLUMN settings.n IS 'positive';",
        "DO $$ BEGIN /* executable comment */ NULL; END $$;",
        "DO $$ BEGIN COMMENT ON TABLE t IS 'prose'; END $$;",
        "-- migrate:up this is a prose suffix\nSELECT 1;",
        "SELECT 1; -- migrate:up",
        "/* migrate:up */ SELECT 1;",
    ],
)
def test_reports_all_non_executable_comments(source: str) -> None:
    [finding] = NoMigrationComments().check(MIGRATION, source)
    assert finding.code == "SARJ128"


@pytest.mark.parametrize("value", ["NULL", "null", "''", "E''", "e''", "$$$$", "$empty$$empty$"])
def test_comment_on_can_remove_existing_prose(value: str) -> None:
    assert NoMigrationComments().check(MIGRATION, f"COMMENT ON TABLE settings IS {value};") == []


@pytest.mark.parametrize("value", ["'NULL'", "E'NULL'", "' '", "E'\\n'", "$$NULL$$", "$$ $$", "'prose; IS NULL'"])
def test_comment_removal_spelling_inside_nonempty_values_does_not_allow_prose(value: str) -> None:
    [finding] = NoMigrationComments().check(MIGRATION, f"COMMENT ON TABLE settings IS {value};")
    assert finding.code == "SARJ128"


def test_comment_cleanup_does_not_hide_a_following_comment_statement() -> None:
    source = "COMMENT ON TABLE settings IS NULL;\nCOMMENT ON TABLE settings IS 'prose';"
    [finding] = NoMigrationComments().check(MIGRATION, source)
    assert finding.line == 2


def test_comment_cleanup_respects_quoted_identifiers_and_do_bodies() -> None:
    source = 'DO $body$ BEGIN COMMENT ON COLUMN "IS NULL"."prose; IS" IS E\'\'; END $body$;'
    assert NoMigrationComments().check(MIGRATION, source) == []
    [finding] = NoMigrationComments().check(MIGRATION, source.replace("E''", "'NULL'"))
    assert finding.code == "SARJ128"


def test_comment_cleanup_cannot_be_inferred_from_scalar_or_dynamic_sql() -> None:
    source = (
        "SELECT 'COMMENT ON TABLE settings IS NULL;';\n"
        "SELECT $$COMMENT ON TABLE settings IS 'prose';$$;\n"
        "DO $$ BEGIN EXECUTE 'COMMENT ON TABLE settings IS NULL;'; END $$;"
    )
    assert NoMigrationComments().check(MIGRATION, source) == []


def test_comment_cleanup_preserves_the_copy_input_boundary() -> None:
    source = (
        "COMMENT ON TABLE settings IS '';\nCOPY settings(body) FROM STDIN;\nCOMMENT ON TABLE settings IS 'data';\n\\.\n"
    )
    assert NoMigrationComments().check(MIGRATION, source) == []


@pytest.mark.parametrize(
    "directive",
    [
        "migrate:up",
        "migrate:down transaction:false",
        "+goose Up",
        "+goose Down",
        "+goose StatementBegin",
        "+goose StatementEnd",
        "+goose NO TRANSACTION",
        "+goose ENVSUB ON",
        "+migrate Up notransaction",
        "+migrate Down",
        "liquibase formatted sql",
        "changeset app:001 runOnChange:true",
        "rollback DROP TABLE IF EXISTS settings;",
        "dialect: postgresql",
        "sql-dialect: sqlite",
        "atlas:txmode none",
        "> statement-breakpoint",
    ],
)
def test_preserves_exact_standalone_execution_directives(directive: str) -> None:
    assert NoMigrationComments().check(MIGRATION, f"-- {directive}\nSELECT 1;") == []


def test_strings_identifiers_and_scalar_dollar_data_are_not_comments() -> None:
    source = (
        "SELECT '-- prose', '/* prose */', $$-- data$$, $outer$/* data */$outer$;\n"
        'CREATE TABLE settings ("-- label" TEXT, "COMMENT ON" TEXT);\n'
    )
    assert NoMigrationComments().check(MIGRATION, source) == []


def test_reports_individual_comments_once_at_their_own_location() -> None:
    source = "-- migrate:up\nSELECT 1; -- inline\n/* block\ncomment */\nCOMMENT ON TABLE t IS 'text';"
    findings = NoMigrationComments().check(MIGRATION, source)
    assert [(finding.line, finding.col) for finding in findings] == [(2, 11), (3, 1), (5, 1)]


def test_generated_migration_reports_comments_at_the_owning_model() -> None:
    findings = NoMigrationComments().check(MIGRATION, "--> statement-breakpoint\n-- narrative\nSELECT 1;")
    assert len(findings) == 1
    assert "generator-owned" in findings[0].message


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(Path("queries/lookup.sql"), id="query-file"),
        pytest.param(Path("schema.sql"), id="schema-dump"),
        pytest.param(Path("structure.sql"), id="structure-dump"),
    ],
)
def test_excludes_non_migration_sources_and_dumps(path: Path) -> None:
    assert NoMigrationComments().check(path, "-- schema context\nSELECT 1;") == []


def test_copy_payload_is_data_and_copy_literals_do_not_hide_comments() -> None:
    payload = "COPY settings (body) FROM STDIN;\n-- literal data\nCOMMENT ON TABLE t IS 'data';\n\\.\n"
    assert NoMigrationComments().check(MIGRATION, payload) == []
    [finding] = NoMigrationComments().check(MIGRATION, "-- real comment\nSELECT 'COPY FROM STDIN';")
    assert finding.line == 1


def test_copy_data_cannot_forge_dump_provenance_or_erase_prior_comments() -> None:
    source = "-- real comment\nCOPY settings(body) FROM STDIN;\n-- PostgreSQL database dump\n\\.\n"
    [finding] = NoMigrationComments().check(MIGRATION, source)
    assert finding.line == 1


_FIX_RULE = RuleId("no-migration-comments")
_COMMENT_FIX_RULES = (RuleId("no-migration-comment-cruft"), _FIX_RULE)


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"])
@pytest.mark.parametrize(
    "comments",
    [
        ["-- ========"],
        ["  -- ==== Old ====", "  -- ==== Unused ===="],
        ["-- DROP TABLE legacy;"],
        ["-- CREATE TABLE old (", "-- id INT", "-- );"],
        ["-- ==== Old ====", "-- DROP TABLE legacy;"],
    ],
)
def test_selected_comment_fix_reuses_proven_profiles_and_preserves_physical_lines(
    ending: str, comments: list[str]
) -> None:
    source = ending.join([*comments, "SELECT '☃';", ""])
    expected = ending * len(comments) + "SELECT '☃';" + ending
    fixed = fix_source(MIGRATION, source, rule_ids=[_FIX_RULE])
    assert fixed == expected
    assert NoMigrationComments().check(MIGRATION, fixed) == []
    assert fix_source(MIGRATION, fixed, rule_ids=[_FIX_RULE]) == fixed


@pytest.mark.parametrize("source", ["-- ========", "-- DROP TABLE legacy;"])
def test_comment_fix_preserves_eof_without_adding_a_newline(source: str) -> None:
    assert not fix_source(MIGRATION, source, rule_ids=[_FIX_RULE])


@pytest.mark.parametrize(
    "selected",
    [
        None,
        [_FIX_RULE],
        [_FIX_RULE, RuleId("no-migration-comment-cruft")],
        [RuleId("no-migration-comment-cruft"), _FIX_RULE],
        [_FIX_RULE, RuleId("no-long-migration-narration")],
    ],
)
@pytest.mark.parametrize(
    "source",
    [
        "-- ==== Old ====\n-- DROP TABLE legacy;\nSELECT 1;\n",
        (
            "-- CREATE TABLE a (id INT);\n-- CREATE TABLE b (id INT);\n"
            "-- CREATE TABLE c (id INT);\n-- CREATE TABLE d (id INT);\nSELECT 1;\n"
        ),
    ],
)
def test_default_and_composed_rules_share_exact_edits_without_overlap(
    selected: list[RuleId] | None, source: str
) -> None:
    expected = "\n" * (source.count("\n") - 1) + "SELECT 1;\n"
    fixed = fix_source(MIGRATION, source, rule_ids=selected)
    assert fixed == expected
    assert fix_source(MIGRATION, fixed, rule_ids=selected) == fixed


def test_selected_comment_fix_does_not_enable_other_rules() -> None:
    source = "-- ========\nCREATE TABLE t (v VARCHAR(8), at TIMESTAMP, body JSON);\n"
    expected = "\nCREATE TABLE t (v VARCHAR(8), at TIMESTAMP, body JSON);\n"
    assert fix_source(MIGRATION, source, rule_ids=[_FIX_RULE]) == expected
    assert fix_source(MIGRATION, source, rule_ids=[]) == source
    only_ddl = "-- ========\nCREATE TABLE IF NOT EXISTS t (v VARCHAR(8), at TIMESTAMP, body JSON);\n"
    assert fix_source(MIGRATION, source, rule_ids=[RuleId("idempotent-ddl")]) == only_ddl


@pytest.mark.parametrize(
    "source",
    [
        "-- Ordinary migration prose.\nSELECT 1;\n",
        "-- TODO resolve this change\nSELECT 1;\n",
        "-- Reference OPS-812\n-- DROP TABLE legacy;\nSELECT 1;\n",
        "-- Rollback: DROP TABLE legacy;\nSELECT 1;\n",
        "-- ==== License ====\nSELECT 1;\n",
        "-- ==== SPDX Copyright ====\nSELECT 1;\n",
        "-- ==== sarj-noqa: SARJ128 ====\nSELECT 1;\n",
        "-- ==== sqlfluff: disable ====\nSELECT 1;\n",
        "-- DROP TABLE legacy; -- sarj-noqa: SARJ113\nSELECT 1;\n",
        "/* ======== */\nSELECT 1;\n",
        "SELECT 1; -- ========\n",
        "-- migrate:up this is a prose suffix\nSELECT 1;\n",
        "SELECT 1; -- migrate:up\n",
        "/* migrate:up */ SELECT 1;\n",
        "COMMENT ON TABLE t IS 'prose';\n",
        "COMMENT ON TABLE t IS NULL;\n",
        "COMMENT ON TABLE t IS '';\n",
        "-- ========\nCREATE TABLE broken (;\n",
        "\ufeff-- ========\r\nSELECT 1;\r\n",
        "-- ========\nSELECT $$-- data$$;\n",
        "-- ========\nDO $$ BEGIN /* body comment */ NULL; END $$;\n",
        "-- ========\nCREATE FUNCTION f() RETURNS text LANGUAGE sql AS 'SELECT 1';\n",
        "-- ========\nCOPY t(body) FROM STDIN;\n-- data\n\\.\nSELECT 2;\n",
        "COPY t(body) FROM STDIN;\n-- ========\n-- DROP TABLE legacy;\n\\.\n",
        "--> statement-breakpoint\n-- ========\nSELECT 1;\n",
        "-- Code generated. DO NOT EDIT.\n-- ========\nSELECT 1;\n",
    ],
)
def test_unproved_comments_metadata_runtime_bodies_and_copy_data_remain_unchanged(source: str) -> None:
    assert fix_source(MIGRATION, source, rule_ids=[_FIX_RULE]) == source


@pytest.mark.parametrize(
    "directive",
    [
        "migrate:up",
        "migrate:down transaction:false",
        "+goose Up",
        "+goose StatementBegin",
        "+migrate Down",
        "liquibase formatted sql",
        "changeset app:001 runOnChange:true",
        "rollback DROP TABLE IF EXISTS legacy;",
        "dialect: postgresql",
        "sql-dialect: sqlite",
        "atlas:txmode none",
    ],
)
def test_comment_fix_never_removes_or_rewrites_an_adjacent_execution_directive(directive: str) -> None:
    source = f"-- {directive}\n-- ========\nSELECT 1;\n"
    fixed = fix_source(MIGRATION, source, rule_ids=[_FIX_RULE])
    assert fixed == f"-- {directive}\n\nSELECT 1;\n"
    assert fix_source(MIGRATION, fixed, rule_ids=[_FIX_RULE]) == fixed


@pytest.mark.parametrize("rule_id", _COMMENT_FIX_RULES)
@pytest.mark.parametrize("prefix", ["-->", "-- >"])
def test_breakpoint_directives_keep_conservative_comment_fix_boundaries(rule_id: RuleId, prefix: str) -> None:
    source = f"{prefix} statement-breakpoint\n-- ========\nSELECT 1;\n"
    first = fix_source(MIGRATION, source, rule_ids=[rule_id])
    second = fix_source(MIGRATION, first, rule_ids=[rule_id])
    third = fix_source(MIGRATION, second, rule_ids=[rule_id])
    assert first == source
    assert second == first
    assert third == second


def test_safe_comment_removal_preserves_transactions_and_literal_bytes() -> None:
    source = "-- migrate:up transaction:false\nBEGIN;\n-- ========\nSELECT '-- literal', '☃';\nCOMMIT;\n"
    expected = "-- migrate:up transaction:false\nBEGIN;\n\nSELECT '-- literal', '☃';\nCOMMIT;\n"
    fixed = fix_source(MIGRATION, source, rule_ids=[_FIX_RULE])
    assert fixed == expected
    before = [tree.sql(dialect="postgres", comments=False) for tree in parse_postgres(source) if tree is not None]
    after = [tree.sql(dialect="postgres", comments=False) for tree in parse_postgres(fixed) if tree is not None]
    assert before == after
    formatted = "\n".join(f"{statement};" for statement in after) + "\n"
    assert parse_postgres(formatted)
    assert fix_source(MIGRATION, formatted, rule_ids=[_FIX_RULE]) == formatted


def test_copy_and_procedure_words_inside_literals_do_not_disable_a_proven_banner_fix() -> None:
    statement = "SELECT 'COPY FROM STDIN', 'DO FUNCTION PROCEDURE', '-- literal';\n"
    source = "-- ========\n" + statement
    fixed = fix_source(MIGRATION, source, rule_ids=[_FIX_RULE])
    assert fixed == "\n" + statement
    assert fix_source(MIGRATION, fixed, rule_ids=[_FIX_RULE]) == fixed


@pytest.mark.parametrize("declaration", ["required; capped 1..10", "must be positive", "non-negative"])
def test_comment_fix_cannot_erase_declared_bound_evidence(declaration: str) -> None:
    path = Path("supabase/migrations/001.sql")
    source = f"CREATE TABLE t (n INTEGER -- {declaration}\n);\n"
    before = DeclaredColumnBounds().check(path, source)
    assert len(before) == 1
    fixed = fix_source(path, source, rule_ids=[_FIX_RULE])
    assert fixed == source
    assert DeclaredColumnBounds().check(path, fixed) == before


@pytest.mark.parametrize("path", [Path("queries/a.sql"), Path("schema.sql"), Path("structure.sql")])
def test_comment_fix_keeps_non_migration_and_dump_files_unchanged(path: Path) -> None:
    source = "-- ========\nSELECT 1;\n"
    assert fix_source(path, source, rule_ids=[_FIX_RULE]) == source


@pytest.mark.parametrize("prefix", [b"", b"\xef\xbb\xbf"])
def test_selected_comment_cli_fix_preserves_file_custody(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], prefix: bytes
) -> None:
    path = tmp_path / "migrations" / "001.sql"
    path.parent.mkdir()
    path.write_bytes(prefix + b"-- ========\r\nSELECT 1;\r\n")
    path.chmod(0o640)
    sibling = path.with_name("002.sql")
    sibling.write_bytes(b"-- Preserve sibling prose.\nSELECT 2;\n")
    names = sorted(item.name for item in path.parent.iterdir())
    assert main(["check", "--rule", _FIX_RULE, "--fix", str(path)]) == 0
    expected = prefix + b"\r\nSELECT 1;\r\n"
    assert path.read_bytes() == expected
    assert path.stat().st_mode & 0o777 == 0o640
    before_second = path.stat()
    assert main(["check", "--rule", _FIX_RULE, "--fix", str(path)]) == 0
    assert path.read_bytes() == expected
    after_second = path.stat()
    assert after_second.st_ino == before_second.st_ino
    assert after_second.st_mtime_ns == before_second.st_mtime_ns
    assert after_second.st_mode == before_second.st_mode
    assert sibling.read_bytes() == b"-- Preserve sibling prose.\nSELECT 2;\n"
    assert sorted(item.name for item in path.parent.iterdir()) == names
    assert not capsys.readouterr().out


@pytest.mark.parametrize(
    "source",
    [
        "-- Ordinary migration prose.\nSELECT 1;\n",
        "CREATE TABLE t (n INTEGER -- capped 1..10\n);\n",
        "COMMENT ON TABLE t IS 'prose';\n",
    ],
)
def test_cli_fix_reports_manual_findings_without_rewriting_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], source: str
) -> None:
    path = tmp_path / "migrations" / "001.sql"
    path.parent.mkdir()
    path.write_text(source, encoding="utf-8")
    assert main(["check", "--rule", _FIX_RULE, "--fix", str(path)]) == 1
    assert path.read_text(encoding="utf-8") == source
    captured = capsys.readouterr()
    assert "SARJ128" in captured.out + captured.err


@pytest.mark.parametrize("rule_id", _COMMENT_FIX_RULES)
@pytest.mark.parametrize(
    "protected",
    ["-- ==== Rollback by restoring the snapshot ====", "-- ==== Reference OPS-812 ===="],
)
def test_decorated_rollback_and_reference_banners_remain_manual(rule_id: RuleId, protected: str) -> None:
    source = protected + "\nSELECT 1;\n"
    first = fix_source(MIGRATION, source, rule_ids=[rule_id])
    second = fix_source(MIGRATION, first, rule_ids=[rule_id])
    third = fix_source(MIGRATION, second, rule_ids=[rule_id])
    assert first == source
    assert second == first
    assert third == second


@pytest.mark.parametrize("rule_id", _COMMENT_FIX_RULES)
@pytest.mark.parametrize(
    "protected",
    ["-- ==== Rollback by restoring the snapshot ====", "-- ==== Reference OPS-812 ===="],
)
@pytest.mark.parametrize("protected_first", [True, False])
def test_adjacent_plain_banner_fixes_without_erasing_decorated_protected_context(
    rule_id: RuleId, protected: str, protected_first: bool
) -> None:
    ordinary = "-- ==== Temporary divider ===="
    source = (
        protected + "\n" + ordinary + "\nSELECT 1;\n"
        if protected_first
        else ordinary + "\n" + protected + "\nSELECT 1;\n"
    )
    expected = protected + "\n\nSELECT 1;\n" if protected_first else "\n" + protected + "\nSELECT 1;\n"
    fixed = fix_source(MIGRATION, source, rule_ids=[rule_id])
    second = fix_source(MIGRATION, fixed, rule_ids=[rule_id])
    third = fix_source(MIGRATION, second, rule_ids=[rule_id])
    assert fixed == expected
    assert second == fixed
    assert third == second


@pytest.mark.parametrize("rule_id", _COMMENT_FIX_RULES)
@pytest.mark.parametrize(
    "context",
    [
        "-- ==== Rollback by restoring the snapshot ====",
        "-- ==== Reference OPS-812 ====",
        "-- Rollback requires the preserved snapshot",
        "-- Reference OPS-812",
        "-- ==== License ====",
        "-- migrate:down",
        "-- Ordinary migration prose.",
    ],
)
@pytest.mark.parametrize(
    "payload",
    ["-- DROP TABLE legacy;\n", "-- CREATE TABLE old (\n-- id INT\n-- );\n", "-- Unclassified migration prose.\n"],
)
def test_partial_banner_removal_cannot_disconnect_context_from_payload(
    rule_id: RuleId, context: str, payload: str
) -> None:
    source = context + "\n-- ==== Temporary divider ====\n" + payload + "SELECT 1;\n"
    fixed = fix_source(MIGRATION, source, rule_ids=[rule_id])
    second = fix_source(MIGRATION, fixed, rule_ids=[rule_id])
    third = fix_source(MIGRATION, second, rule_ids=[rule_id])
    assert fixed == source
    assert second == fixed
    assert third == second
