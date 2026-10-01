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
