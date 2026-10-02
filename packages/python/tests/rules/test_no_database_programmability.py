from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sarj_rule_contracts import EvaluationCase, ExpectedOutcome, Language

from sarj_python_lint.__main__ import main
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules.no_database_programmability import NoDatabaseProgrammability


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import RuleExample


_FUNCTION = (
    "CREATE FUNCTION fail_counter() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'failure'; END $$"
)
_TRIGGER = "CREATE TRIGGER fail_counter BEFORE UPDATE ON batch FOR EACH ROW EXECUTE FUNCTION fail_counter()"
_BAD = f"async def install(conn):\n    await conn.execute({_FUNCTION!r})\n"
_CASES = (
    EvaluationCase("fault-fixture", Language.PYTHON, _BAD, ExpectedOutcome.MATCH),
    EvaluationCase("trigger", Language.PYTHON, _BAD.replace(_FUNCTION, _TRIGGER), ExpectedOutcome.MATCH),
    EvaluationCase(
        "replace-function",
        Language.PYTHON,
        _BAD.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "constraint-trigger",
        Language.PYTHON,
        _BAD.replace(_FUNCTION, _TRIGGER.replace("CREATE TRIGGER", "CREATE CONSTRAINT TRIGGER")),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "enable-trigger",
        Language.PYTHON,
        _BAD.replace(_FUNCTION, "ALTER TABLE batch ENABLE ALWAYS TRIGGER fail_counter"),
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("keyword-query", Language.PYTHON, _BAD.replace("execute(", "execute(query="), ExpectedOutcome.MATCH),
    EvaluationCase("executemany", Language.PYTHON, _BAD.replace("execute", "executemany"), ExpectedOutcome.MATCH),
    EvaluationCase(
        "split-literal",
        Language.PYTHON,
        'conn.execute("CREATE " + "FUNCTION fail_counter() RETURNS int LANGUAGE SQL AS $$ SELECT 1 $$")',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "f-string",
        Language.PYTHON,
        'conn.execute(f"CREATE TRIGGER {name} BEFORE UPDATE ON batch EXECUTE FUNCTION fail_counter()")',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "format-string",
        Language.PYTHON,
        'conn.execute("CREATE TRIGGER {} BEFORE UPDATE ON batch EXECUTE FUNCTION fail_counter()".format(name))',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "sql-alias",
        Language.PYTHON,
        f"from psycopg.sql import SQL as statement\nquery = statement({_FUNCTION!r})\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "sql-module",
        Language.PYTHON,
        f"from psycopg import sql\nconn.execute(sql.SQL({_TRIGGER!r}).format())\n",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "declarative-fault",
        Language.PYTHON,
        _BAD.replace(_FUNCTION, "ALTER TABLE batch ADD CONSTRAINT fail_counter CHECK (false) NOT VALID"),
    ),
    EvaluationCase("drop-function", Language.PYTHON, _BAD.replace(_FUNCTION, "DROP FUNCTION fail_counter()")),
    EvaluationCase(
        "disable-trigger", Language.PYTHON, _BAD.replace(_FUNCTION, "ALTER TABLE batch DISABLE TRIGGER fail_counter")
    ),
    EvaluationCase("builtin-call", Language.PYTHON, _BAD.replace(_FUNCTION, "SELECT uuidv7()")),
    EvaluationCase("sql-comment", Language.PYTHON, _BAD.replace(_FUNCTION, "-- CREATE FUNCTION example()")),
    EvaluationCase("quoted-value", Language.PYTHON, "conn.execute(\"SELECT 'CREATE TRIGGER example'\")"),
    EvaluationCase("dollar-value", Language.PYTHON, 'conn.execute("SELECT $$CREATE FUNCTION example()$$")'),
    EvaluationCase(
        "escape-string-value", Language.PYTHON, "conn.execute(\"SELECT E'escaped \\\\' ; CREATE FUNCTION example()'\")"
    ),
    EvaluationCase(
        "escape-string-trigger-value",
        Language.PYTHON,
        "conn.execute(\"SELECT e'escaped \\\\' ; CREATE TRIGGER example'\")",
    ),
    EvaluationCase(
        "escape-string-followed-by-ddl",
        Language.PYTHON,
        f"conn.execute({("SELECT E'escaped \\' value'; " + _FUNCTION)!r})",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "dollar-in-identifier-followed-by-ddl",
        Language.PYTHON,
        'conn.execute("SELECT foo$tag$ FROM docs; CREATE FUNCTION forbidden() RETURNS int LANGUAGE SQL AS $$ SELECT 1 $$")',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "dollar-in-identifier-before-matching-body-tag",
        Language.PYTHON,
        'conn.execute("SELECT foo$body$ FROM docs; CREATE FUNCTION forbidden() RETURNS int AS $body$ SELECT 1 $body$ LANGUAGE SQL")',
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase(
        "standard-string-backslash-before-ddl",
        Language.PYTHON,
        f"conn.execute({("SELECT 'backslash \\' ; " + _FUNCTION)!r})",
        ExpectedOutcome.MATCH,
    ),
    EvaluationCase("prose", Language.PYTHON, 'conn.execute("Explain why CREATE TRIGGER is banned")'),
    EvaluationCase(
        "nested-sql-comment", Language.PYTHON, f"conn.execute({'/* outer /* inner */ ' + _FUNCTION + ' */'!r})"
    ),
    EvaluationCase("test-data", Language.PYTHON, f"example = {_FUNCTION!r}\n"),
    EvaluationCase("python-function", Language.PYTHON, 'def create_function():\n    return "trigger"\n'),
    EvaluationCase("generated", Language.PYTHON, "# @generated\n" + _BAD),
    EvaluationCase("malformed-python", Language.PYTHON, "def install(:"),
    EvaluationCase("dynamic-query", Language.PYTHON, "conn.execute(build_statement())"),
)


@pytest.mark.parametrize("case", _CASES, ids=tuple(case.case_id for case in _CASES))
def test_labeled_embedded_sql_policy(case: EvaluationCase) -> None:
    findings = NoDatabaseProgrammability().check(Path("tests/fakes/batch_fault.py"), case.source)
    assert bool(findings) is (case.expected is ExpectedOutcome.MATCH)


def test_one_blocking_diagnostic_per_execution_including_composed_sql() -> None:
    source = f"from psycopg import sql\nconn.execute(sql.SQL({_FUNCTION!r}))\nconn.execute({_TRIGGER!r})\n"
    findings = NoDatabaseProgrammability().check(Path("app/store.py"), source)
    assert [(item.code, item.line, item.severity) for item in findings] == [
        ("SARJ470", 2, Severity.ERROR),
        ("SARJ470", 3, Severity.ERROR),
    ]


def test_reasoned_exact_suppression() -> None:
    source = _BAD.rstrip() + "  # sarj-noqa: SARJ470 -- approved compatibility migration\n"
    assert NoDatabaseProgrammability().check(Path("app/store.py"), source) == []


def test_cli_blocks_embedded_ddl(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "fault.py"
    path.write_text(_BAD)
    assert main(["check", "--rule", "no-database-programmability", str(path)]) == 1
    assert "SARJ470" in capsys.readouterr().out
    path.write_text(_BAD.rstrip() + "  # sarj-noqa: SARJ470 -- approved compatibility migration\n")
    assert main(["check", "--rule", "no-database-programmability", str(path)]) == 0


@pytest.mark.parametrize("example", NoDatabaseProgrammability.public_examples())
def test_public_examples(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoDatabaseProgrammability().check(Path(str(focus.path)), focus.source)) == example.expected_count
