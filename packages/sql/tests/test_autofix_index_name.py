from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts import RuleId
from sqlglot import exp

from sarj_sql_lint.__main__ import main
from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.autofix import fix_source
from sarj_sql_lint.rules._index_analysis import parse_indexes
from sarj_sql_lint.rules.invalid_postgres_ddl import InvalidPostgresDdl


_PATH = Path("migrations/001_index.sql")
_RULES = [RuleId(InvalidPostgresDdl.id)]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("CREATE INDEX app.item_key ON app.item(id);", "CREATE INDEX item_key ON app.item(id);"),
        ('CREATE INDEX APP.item_key ON "app".item(id);', 'CREATE INDEX item_key ON "app".item(id);'),
        ('CREATE INDEX "App"."ItemKey" ON "App"."Item"(id);', 'CREATE INDEX "ItemKey" ON "App"."Item"(id);'),
        ('CREATE INDEX "a.b"."item;key" ON "a.b".item(id);', 'CREATE INDEX "item;key" ON "a.b".item(id);'),
        ('CREATE INDEX "a""b".item_key ON "a""b".item(id);', 'CREATE INDEX item_key ON "a""b".item(id);'),
        ("CREATE UNIQUE INDEX app.item_key ON app.item(id);", "CREATE UNIQUE INDEX item_key ON app.item(id);"),
        (
            "CREATE INDEX CONCURRENTLY app.item_key ON app.item(id);",
            "CREATE INDEX CONCURRENTLY item_key ON app.item(id);",
        ),
        (
            "CREATE INDEX IF NOT EXISTS app.item_key ON app.item USING btree(id DESC) INCLUDE(label) WHERE active;",
            "CREATE INDEX IF NOT EXISTS item_key ON app.item USING btree(id DESC) INCLUDE(label) WHERE active;",
        ),
    ],
    ids=[
        "plain",
        "folded-schema",
        "quoted-case",
        "quoted-punctuation",
        "escaped-quote",
        "unique",
        "concurrent",
        "clauses",
    ],
)
def test_explicit_same_schema_syntax_repair(source: str, expected: str) -> None:
    before = parse_indexes(source)
    fixed = fix_source(_PATH, source, rule_ids=_RULES)
    assert fixed == expected
    assert InvalidPostgresDdl().check(_PATH, fixed) == []
    assert fix_source(_PATH, fixed, rule_ids=_RULES) == fixed
    assert len(before) == len(after := parse_indexes(fixed)) == 1
    assert before[0].signature == after[0].signature
    parsed = parse_postgres(fixed)
    assert len(parsed) == 1
    assert isinstance(parsed[0], exp.Create)
    assert parsed[0].args.get("kind") == "INDEX"
    assert parsed[0].find(exp.Command) is None


@pytest.mark.parametrize(
    "source",
    [
        "CREATE INDEX app.item_key ON item(id);",
        "CREATE INDEX app.item_key ON other.item(id);",
        'CREATE INDEX "App".item_key ON app.item(id);',
        "CREATE INDEX catalog.app.item_key ON app.item(id);",
        "CREATE INDEX app.item_key ON catalog.app.item(id);",
        "CREATE INDEX app.item_key ON ONLY app.item(id);",
        "CREATE INDEX app.item_key ON app.item(id); SELECT 1;",
        "CREATE INDEX app.item_key ON app.item(id); CREATE INDEX app.other_key ON app.item(label);",
        "CREATE UNIQUE INDEX app.item_key ON app.item USING hash(id);",
        "CREATE INDEX app.item_key ON app.item(id) INCLUDE(lower(label));",
        "CREATE INDEX app.item_key ON app.item USING hash(a,b);",
        "CREATE INDEX app.item_key ON app.item(",
        "CREATE INDEX app.item_key ON app.item(id) trailing invalid syntax;",
        "CREATE INDEX app. ON app.item(id);",
        "ALTER TABLE app.item ADD UNIQUE(id) NOT VALID;",
        "SELECT 'CREATE INDEX app.item_key ON app.item(id);';",
        "DO $$ BEGIN CREATE INDEX app.item_key ON app.item(id); END $$;",
    ],
    ids=[
        "unqualified-table",
        "different-schema",
        "case-distinction",
        "catalog-index",
        "catalog-table",
        "only-table",
        "second-statement",
        "second-index",
        "unsupported-unique-method",
        "invalid-include",
        "invalid-key-count",
        "malformed",
        "invalid-suffix",
        "missing-name",
        "constraint",
        "string",
        "routine",
    ],
)
def test_unproven_or_other_invalid_contract_is_preserved(source: str) -> None:
    assert fix_source(_PATH, source, rule_ids=_RULES) == source


@pytest.mark.parametrize(
    "prefix",
    [
        "-- retain the qualified spelling\n",
        "/* owned index */ ",
        "-- sarj-noqa: SARJ126 -- compatible database fork\n",
        "-- dialect: mysql\n",
        "-- @generated\n",
        "-- PostgreSQL database dump\n",
        "--> statement-breakpoint\n",
    ],
    ids=["line-comment", "block-comment", "suppression", "other-dialect", "generated", "dump", "generator"],
)
def test_comments_suppressions_and_non_authored_sources_are_preserved(prefix: str) -> None:
    source = prefix + "CREATE INDEX app.item_key ON app.item(id);"
    assert fix_source(_PATH, source, rule_ids=_RULES) == source


@pytest.mark.parametrize(
    "path",
    [Path("tests/index.sql"), Path("fixtures/index.sql"), Path("migrations/001.generated.sql")],
    ids=["test-source", "fixture-source", "generated-migration"],
)
def test_external_ownership_is_preserved(path: Path) -> None:
    source = "CREATE INDEX app.item_key ON app.item(id);"
    assert fix_source(path, source, rule_ids=_RULES) == source


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
def test_prefix_only_edit_preserves_physical_lines(ending: str) -> None:
    source = f"CREATE INDEX app{ending}.item_key ON app.item(id);{ending}"
    expected = f"CREATE INDEX {ending}item_key ON app.item(id);{ending}"
    fixed = fix_source(_PATH, source, rule_ids=_RULES)
    assert fixed == expected
    assert fix_source(_PATH, fixed, rule_ids=_RULES) == fixed


def test_mixed_lines_remain_exact() -> None:
    source = "CREATE INDEX app\r\n.\ritem_key ON app.item(id);\n"
    expected = "CREATE INDEX \r\n\ritem_key ON app.item(id);\n"
    assert fix_source(_PATH, source, rule_ids=_RULES) == expected


@pytest.mark.parametrize("rule_ids", [[], [RuleId("idempotent-ddl")]], ids=["empty-selection", "different-rule"])
def test_unselected_repair_does_not_change_unparseable_source(rule_ids: list[RuleId]) -> None:
    source = "CREATE INDEX app.item_key ON app.item(id);"
    assert fix_source(_PATH, source, rule_ids=rule_ids) == source


def test_fix_budget_abstains() -> None:
    source = " " * 8192 + "CREATE INDEX app.item_key ON app.item(id);"
    assert fix_source(_PATH, source, rule_ids=_RULES) == source


def test_real_cli_selected_fix_preserves_mode_and_crlf(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "migration.sql"
    path.write_bytes(b"CREATE INDEX app.item_key ON app.item(id);\r\n")
    path.chmod(0o755)
    original_mode = path.stat().st_mode & 0o777
    assert main(["check", "--rule", InvalidPostgresDdl.id, "--fix", str(path)]) == 0
    assert path.read_bytes() == b"CREATE INDEX item_key ON app.item(id);\r\n"
    assert path.stat().st_mode & 0o777 == original_mode
    assert not capsys.readouterr().out
