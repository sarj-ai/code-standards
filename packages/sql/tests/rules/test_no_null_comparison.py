from __future__ import annotations

from pathlib import Path

import pytest
from sarj_rule_contracts.examples import verify_native_rule

from sarj_sql_lint.__main__ import analyze, main
from sarj_sql_lint.rule_base import DefaultLevel
from sarj_sql_lint.rules.no_null_comparison import NoNullComparison


P = Path("queries/events.sql")


def test_documented_examples() -> None:
    verify_native_rule(NoNullComparison, analyze)


@pytest.mark.parametrize("operator", ["=", "<>", "!=", "<", "<=", ">", ">="])
@pytest.mark.parametrize(
    "operands",
    [
        "value {operator} NULL",
        "NULL {operator} value",
        "value {operator} ((NULL))",
        "value {operator} +NULL",
        "+((NULL)) {operator} value",
    ],
)
def test_bare_null_comparisons(operator: str, operands: str) -> None:
    source = "SELECT id FROM event WHERE " + operands.format(operator=operator) + ";"  # ruff: ignore[hardcoded-sql-expression] -- fixed parser fixture, never executed.
    findings = NoNullComparison().check(P, source)
    assert len(findings) == 1


@pytest.mark.parametrize(
    "predicate",
    ["value NOT IN (1, NULL)", "value NOT IN ((NULL), 1)", "NOT value IN (1,NULL)", "value NOT IN (NULL, NULL)"],
)
def test_literal_null_exclusion_lists(predicate: str) -> None:
    source = f"SELECT id FROM event WHERE {predicate};"  # ruff: ignore[hardcoded-sql-expression] -- fixed parser fixture, never executed.
    assert len(NoNullComparison().check(P, source)) == 1


@pytest.mark.parametrize(
    "predicate",
    [
        "value IS NULL",
        "value IS NOT NULL",
        "value IS DISTINCT FROM NULL",
        "value IS NOT DISTINCT FROM NULL",
        "value = 'NULL'",
        '"NULL" = value',
        "value = $1",
        "value = COALESCE(NULL, 1)",
        "value IN (NULL, 1)",
        "value NOT IN (SELECT other FROM event)",
        "value NOT IN (1, 2)",
        "(a,b) NOT IN ((1,NULL))",
        "ROW(1,2) NOT IN (NULL)",
        "((ROW(1,2))) NOT IN (NULL)",
        "value NOT IN (ROW(1,NULL))",
        "value = NULL::integer",
        "value = CAST(NULL AS integer)",
        "value OPERATOR(custom.=) NULL",
        "value = (",
        "value =",
    ],
)
def test_near_misses(predicate: str) -> None:
    source = f"SELECT id FROM event WHERE {predicate};"  # ruff: ignore[hardcoded-sql-expression] -- fixed parser fixture, never executed.
    assert NoNullComparison().check(P, source) == []


@pytest.mark.parametrize(
    "source",
    [
        "-- SELECT value = NULL;\nSELECT 1;",
        "SELECT 'value = NULL';",
        "SELECT $$value = NULL;$$;",
        "DO $$ BEGIN PERFORM value = NULL; END $$;",
        "SELECT 1 /* SELECT value = NULL */;",
    ],
)
def test_comments_literals_and_procedural_bodies(source: str) -> None:
    assert NoNullComparison().check(P, source) == []


def test_one_finding_per_expression_and_original_locations() -> None:
    source = "SELECT 1;\r\nSELECT a = NULL, b <> (NULL), c NOT IN (NULL, NULL);"
    findings = NoNullComparison().check(P, source)
    assert [(finding.line, finding.col) for finding in findings] == [(2, 12), (2, 24), (2, 41)]


@pytest.mark.parametrize(
    "source",
    [
        "UPDATE event SET value = NULL WHERE id = NULL;",
        "DELETE FROM event WHERE id = NULL;",
        "INSERT INTO event(id) SELECT id FROM other WHERE id = NULL;",
        "CREATE TABLE event (id BIGINT CHECK (id <> NULL));",
    ],
)
def test_query_and_migration_statements(source: str) -> None:
    assert len(NoNullComparison().check(Path("supabase/migrations/001.sql"), source)) == 1


def test_bad_statement_does_not_hide_following_valid_statement() -> None:
    assert len(NoNullComparison().check(P, "SELECT ( ; SELECT value = NULL;")) == 1


@pytest.mark.parametrize("predicate", ["((NULL)) < value", "value NOT IN (NULL, 1)"])
def test_declaration_nulls_do_not_hide_a_later_query(predicate: str) -> None:
    declarations = "\n".join(
        f"CREATE TABLE item_{index} (id BIGINT NOT NULL, value TEXT DEFAULT NULL);" for index in range(80)
    )
    source = f"{declarations}\nSELECT id FROM event WHERE {predicate};"
    findings = NoNullComparison().check(P, source)
    assert len(findings) == 1
    assert findings[0].line == 81


@pytest.mark.parametrize(
    "prefix",
    [
        "SELECT 'literal; NULL = value';",
        'SELECT "column;NULL" FROM event;',
        "SELECT $text$NULL = value;$text$;",
        "DO $$ BEGIN PERFORM value = NULL; END $$;",
        "SELECT 1 /* ; value = NULL */;",
        "-- NULL = value;\nSELECT 1;",
        "SELECT 1; -- {{ NULL = value; }}",
    ],
)
def test_opaque_semicolons_preserve_following_query_locations(prefix: str) -> None:
    tail = "SELECT value = +((NULL));"
    findings = NoNullComparison().check(P, f"{prefix}\r\n{tail}")
    assert [(finding.line, finding.col) for finding in findings] == [(prefix.count("\n") + 2, tail.index("NULL") + 1)]


def test_later_lexical_failure_does_not_hide_an_earlier_statement() -> None:
    findings = NoNullComparison().check(P, "SELECT value = NULL;\nSELECT 'unterminated")
    assert len(findings) == 1
    assert findings[0].line == 1


@pytest.mark.parametrize(
    ("path", "prefix"),
    [
        (Path("schema.sql"), ""),
        (Path("tests/events.sql"), ""),
        (P, "-- dialect: sqlite\n"),
        (P, "-- @generated\n"),
        (P, "-- PostgreSQL database dump\n"),
        (Path("supabase/migrations/001.sql"), "--> statement-breakpoint\n"),
    ],
)
def test_external_ownership_and_dialects(path: Path, prefix: str) -> None:
    assert NoNullComparison().check(path, prefix + "SELECT value = NULL;") == []


def test_warning_and_exact_suppression(tmp_path: Path) -> None:
    target = tmp_path / "events.sql"
    target.write_text("SELECT value = NULL;\n")
    result = analyze([NoNullComparison.id], [target])
    assert len(result) == 1
    assert result[0].severity is DefaultLevel.WARNING
    assert main(["check", "--rule", NoNullComparison.id, str(target)]) == 0
    target.write_text("SELECT value = NULL; -- sarj-noqa: SARJ124 -- intentional unknown boolean\n")
    assert analyze([NoNullComparison.id], [target]) == []
