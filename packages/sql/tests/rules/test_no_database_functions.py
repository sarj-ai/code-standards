from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_sql_lint.__main__ import main
from sarj_sql_lint.rules.no_create_trigger import NoCreateTrigger
from sarj_sql_lint.rules.no_database_functions import NoDatabaseFunctions


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import RuleExample


_BAD = "CREATE FUNCTION fail_counter() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'failure'; END $$;"
_CASES = (
    EvaluationCase("fault-fixture", Language.SQL, _BAD, ExpectedOutcome.MATCH),
    EvaluationCase("replace", Language.SQL, _BAD.replace("CREATE", "CREATE OR REPLACE"), ExpectedOutcome.MATCH),
    EvaluationCase("lowercase", Language.SQL, _BAD.lower(), ExpectedOutcome.MATCH),
    EvaluationCase(
        "schema-qualified", Language.SQL, _BAD.replace("fail_counter", "pg_temp.fail_counter"), ExpectedOutcome.MATCH
    ),
    EvaluationCase("quoted-name", Language.SQL, _BAD.replace("fail_counter", '"fail_counter"'), ExpectedOutcome.MATCH),
    EvaluationCase(
        "comments-between-tokens",
        Language.SQL,
        _BAD.replace("CREATE FUNCTION", "CREATE /* policy */ FUNCTION"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("drop", Language.SQL, "DROP FUNCTION IF EXISTS fail_counter();"),
    EvaluationCase("builtin-call", Language.SQL, "SELECT uuidv7();"),
    EvaluationCase(
        "constraint", Language.SQL, "ALTER TABLE batch ADD CONSTRAINT fail_counter CHECK (false) NOT VALID;"
    ),
    EvaluationCase("comment", Language.SQL, "-- " + _BAD),
    EvaluationCase("nested-comment", Language.SQL, "/* outer /* inner */ " + _BAD + " */"),
    EvaluationCase("quoted-value", Language.SQL, "SELECT 'CREATE FUNCTION example()';"),
    EvaluationCase("dollar-value", Language.SQL, "SELECT $doc$CREATE FUNCTION example()$doc$;"),
    EvaluationCase("dollar-value-with-statement", Language.SQL, "SELECT $doc$; CREATE FUNCTION example()$doc$;"),
    EvaluationCase(
        "dollar-insert-value", Language.SQL, "INSERT INTO docs VALUES ($doc$; CREATE FUNCTION example()$doc$);"
    ),
    EvaluationCase("dollar-comment-value", Language.SQL, "COMMENT ON TABLE docs IS $$; CREATE FUNCTION example()$$;"),
    EvaluationCase(
        "dollar-followed-by-function",
        Language.SQL,
        "SELECT $$; CREATE FUNCTION example()$$;\n" + _BAD,
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("quoted-identifier", Language.SQL, 'SELECT "CREATE FUNCTION example";'),
    EvaluationCase("prose", Language.SQL, "-- Keep CREATE FUNCTION out of application migrations."),
    EvaluationCase("non-postgres", Language.SQL, "-- dialect: mysql\n" + _BAD),
    EvaluationCase("incomplete", Language.SQL, "CREATE"),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_function_policy(case: EvaluationCase) -> None:
    findings = NoDatabaseFunctions().check(Path("supabase/migrations/001.sql"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)


def test_each_statement_has_one_diagnostic_without_trigger_overlap() -> None:
    source = (
        _BAD
        + "\nCREATE OR REPLACE FUNCTION other() RETURNS int AS $$ SELECT 1 $$ LANGUAGE SQL;\nCREATE TRIGGER guard BEFORE UPDATE ON batch EXECUTE FUNCTION fail_counter();"
    )
    findings = NoDatabaseFunctions().check(Path("supabase/migrations/001.sql"), source)
    assert [(item.code, item.line) for item in findings] == [("SARJ120", 1), ("SARJ120", 2)]
    assert len(NoCreateTrigger().check(Path("supabase/migrations/001.sql"), source)) == 1


def test_function_body_documentation_does_not_create_extra_findings() -> None:
    source = "CREATE FUNCTION docs() RETURNS text AS $body$ SELECT $doc$; CREATE FUNCTION example()$doc$; $body$ LANGUAGE SQL;"
    assert len(NoDatabaseFunctions().check(Path("supabase/migrations/001.sql"), source)) == 1


def test_dump_is_excluded() -> None:
    assert NoDatabaseFunctions().check(Path("schema.sql"), _BAD) == []


def test_exact_suppression_and_blocking_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "001.sql"
    path.write_text("-- dialect: postgres\n" + _BAD)
    assert main(["check", "--rule", "no-database-functions", str(path)]) == 1
    assert "SARJ120" in capsys.readouterr().out
    path.write_text("-- dialect: postgres\n" + _BAD + " -- sarj-noqa: SARJ120 -- approved compatibility migration")
    assert main(["check", "--rule", "no-database-functions", str(path)]) == 0


@pytest.mark.parametrize("example", NoDatabaseFunctions.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoDatabaseFunctions().check(Path(str(focus.path)), focus.source)) == example.expected_count


def test_database_owned_index_invariant_cannot_waive_the_migration_ban(tmp_path: Path) -> None:
    source = (
        "CREATE FUNCTION normalized_key(value text) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT lower(value) $$;"
    )
    findings = NoDatabaseFunctions().check(Path("supabase/migrations/001.sql"), source)
    assert len(findings) == 1
    assert "atomicity" in findings[0].message
    assert "cannot waive" in findings[0].message
    path = tmp_path / "migrations" / "001.sql"
    path.parent.mkdir()
    path.write_text(
        "-- dialect: postgres\n"
        + source
        + " -- sarj-noqa: SARJ120 -- approved database-owned uniqueness invariant\n"
        + "CREATE UNIQUE INDEX IF NOT EXISTS widget_key ON widget (normalized_key(name));\n"
    )
    assert main(["check", "--rule", "no-database-functions", str(path)]) == 1


@pytest.mark.parametrize(
    "source",
    [
        "DO $outer$ BEGIN CREATE FUNCTION app.f() RETURNS integer LANGUAGE sql AS $inner$SELECT 1$inner$; END $outer$;",
        "DO $outer$ BEGIN CREATE OR REPLACE FUNCTION app.f() RETURNS integer LANGUAGE sql AS $inner$SELECT 1$inner$; END $outer$;",
    ],
)
def test_executable_anonymous_block_cannot_hide_a_stored_function(source: str) -> None:
    [finding] = NoDatabaseFunctions().check(Path("migrations/001.sql"), source)
    assert (finding.line, finding.col) == (1, source.index("CREATE") + 1)


def test_scalar_dollar_data_cannot_create_a_stored_function() -> None:
    source = "SELECT $outer$CREATE FUNCTION app.f() RETURNS integer LANGUAGE sql AS $inner$SELECT 1$inner$;$outer$;"
    assert NoDatabaseFunctions().check(Path("migrations/001.sql"), source) == []


def test_every_function_in_an_anonymous_block_keeps_its_absolute_location() -> None:
    source = (
        "DO $outer$ BEGIN CREATE FUNCTION app.f() RETURNS integer LANGUAGE sql AS $inner$SELECT 1$inner$; "
        "CREATE FUNCTION app.g() RETURNS integer LANGUAGE sql AS $inner$SELECT 2$inner$; END $outer$;"
    )
    findings = NoDatabaseFunctions().check(Path("migrations/001.sql"), source)
    first = source.index("CREATE")
    second = source.index("CREATE", first + 1)
    assert [(item.line, item.col) for item in findings] == [(1, first + 1), (1, second + 1)]


@pytest.mark.parametrize(
    "source",
    [
        "SELECT x$CREATE FUNCTION FROM docs;",
        "SELECT x\u0301CREATE FUNCTION FROM docs;",
        "SELECT CREATE FUNCTION$label FROM docs;",
        "SELECT CREATE FUNCTION\u0301 FROM docs;",
        "SELECT CREATE FUNCTİON FROM docs;",
    ],
)
def test_identifier_parts_are_not_routine_keywords(source: str) -> None:
    assert NoDatabaseFunctions().check(Path("supabase/migrations/001.sql"), source) == []


@pytest.mark.parametrize("prefix", ["CREATE", "CREATE OR REPLACE"])
def test_procedures_are_banned_with_functions(prefix: str) -> None:
    source = f"{prefix} PROCEDURE record_call() LANGUAGE sql AS $$ SELECT 1 $$;"
    assert len(NoDatabaseFunctions().check(Path("supabase/migrations/001.sql"), source)) == 1


def test_copy_input_is_not_executable_routine_ddl() -> None:
    source = f"COPY seed(body) FROM STDIN;\n{_BAD}\n\\.\n{_BAD}"
    rule = NoDatabaseFunctions()
    path = Path("supabase/migrations/001.sql")
    assert rule.check(path, source) == []
    assert len(rule.check(path, f"{_BAD}\n{source}")) == 1
