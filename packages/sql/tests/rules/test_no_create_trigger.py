from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_sql_lint.rules.no_create_trigger import NoCreateTrigger


if TYPE_CHECKING:
    from sarj_sql_lint.rule_base import Diagnostic, RuleExample


def _check(source: str, path: str = "supabase/migrations/001.sql") -> list[Diagnostic]:
    return NoCreateTrigger().check(Path(path), source)


_PUBLIC_EXAMPLES = NoCreateTrigger.public_examples()


@pytest.mark.parametrize("example", _PUBLIC_EXAMPLES, ids=tuple(item.example_id for item in _PUBLIC_EXAMPLES))
def test_public_documentation_examples_are_executable(example: RuleExample) -> None:
    focus = example.focus_file
    assert len(NoCreateTrigger().check(Path(focus.path), focus.source)) == example.expected_count


@pytest.mark.parametrize(
    "source",
    [
        "CREATE TRIGGER update_timestamp BEFORE UPDATE ON calls EXECUTE FUNCTION set_timestamp();",
        "create or replace trigger audit_call after insert on calls execute function audit_call();",
        "CREATE CONSTRAINT TRIGGER tenant_guard AFTER INSERT ON child DEFERRABLE EXECUTE FUNCTION check_tenant();",
        "CREATE EVENT TRIGGER ddl_audit ON ddl_command_start EXECUTE FUNCTION audit_ddl();",
    ],
)
def test_reports_postgres_trigger_creation(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ114"


@pytest.mark.parametrize(
    "source",
    [
        "ALTER TABLE calls ENABLE TRIGGER audit_call;",
        "ALTER TABLE calls ENABLE ALWAYS TRIGGER audit_call;",
        "ALTER TABLE calls ENABLE REPLICA TRIGGER audit_call;",
        "ALTER EVENT TRIGGER ddl_audit ENABLE ALWAYS;",
    ],
)
def test_reports_trigger_reenablement(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "ALTER TRIGGER audit_call ON calls RENAME TO next_audit;",
        "ALTER TRIGGER audit_call ON calls DEPENDS ON EXTENSION audit_extension;",
        "ALTER TRIGGER audit_call ON calls NO DEPENDS ON EXTENSION audit_extension;",
        "ALTER EVENT TRIGGER ddl_audit OWNER TO app;",
        'ALTER EVENT TRIGGER "ddl_audit" RENAME TO next_audit;',
    ],
)
def test_reports_trigger_definition_changes(source: str) -> None:
    [finding] = _check(source)
    assert finding.code == "SARJ114"


@pytest.mark.parametrize(
    "source",
    [
        "-- CREATE TRIGGER is intentionally forbidden",
        "INSERT INTO docs(body) VALUES ('CREATE TRIGGER example');",
        "DROP TRIGGER IF EXISTS update_timestamp ON calls;",
        "ALTER TABLE calls DISABLE TRIGGER audit_call;",
        "ALTER EVENT TRIGGER ddl_audit DISABLE;",
        "DROP EVENT TRIGGER IF EXISTS ddl_audit;",
        "CREATE TABLE trigger_audit (id uuid PRIMARY KEY);",
        "SELECT $$CREATE TRIGGER example$$;",
        "SELECT $doc$; CREATE TRIGGER example$doc$;",
        "INSERT INTO docs VALUES ($doc$CREATE TRIGGER example$doc$);",
        "COMMENT ON TABLE docs IS $$ALTER TABLE batch ENABLE TRIGGER example$$;",
        "DO $$ BEGIN RAISE NOTICE $doc$CREATE TRIGGER example$doc$; END $$;",
        "CREATE FUNCTION docs() RETURNS text AS $body$ SELECT $doc$CREATE TRIGGER example$doc$; $body$ LANGUAGE SQL;",
        "-- ALTER TRIGGER audit_call ON calls RENAME TO next_audit;",
        "SELECT 'ALTER EVENT TRIGGER ddl_audit OWNER TO app;';",
        "SELECT $$ALTER EVENT TRIGGER ddl_audit RENAME TO next_audit;$$;",
    ],
)
def test_ignores_non_executable_trigger_creation(source: str) -> None:
    assert _check(source) == []


def test_skips_non_postgres_dialects() -> None:
    assert _check("-- dialect: mysql\nCREATE TRIGGER audit BEFORE INSERT ON calls FOR EACH ROW SET @x = 1;") == []


def test_reports_each_trigger_statement() -> None:
    source = """
CREATE TRIGGER first AFTER INSERT ON calls EXECUTE FUNCTION first_fn();
CREATE TRIGGER second AFTER UPDATE ON calls EXECUTE FUNCTION second_fn();
"""
    assert [finding.line for finding in _check(source)] == [2, 3]


@pytest.mark.parametrize(
    "source",
    [
        "DO $$ BEGIN CREATE TRIGGER audit AFTER INSERT ON batch EXECUTE FUNCTION audit(); END $$;",
        "DO LANGUAGE plpgsql $body$ BEGIN ALTER TABLE batch ENABLE TRIGGER audit; END $body$;",
        "DO LANGUAGE 'plpgsql' $body$ BEGIN ALTER TABLE batch ENABLE TRIGGER audit; END $body$;",
        'DO /* code */ LANGUAGE "plpgsql" $body$ BEGIN CREATE TRIGGER audit AFTER INSERT ON batch EXECUTE FUNCTION audit(); END $body$;',
        "SELECT $doc$CREATE TRIGGER example$doc$; CREATE TRIGGER audit AFTER INSERT ON batch EXECUTE FUNCTION audit();",
        "DO $$ BEGIN ALTER TRIGGER audit ON batch RENAME TO next_audit; END $$;",
        "DO $$ BEGIN ALTER EVENT TRIGGER ddl_audit OWNER TO app; END $$;",
    ],
)
def test_genuine_trigger_ddl_survives_dollar_literal_masking(source: str) -> None:
    assert len(_check(source)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "SELECT x$CREATE TRIGGER FROM docs;",
        "SELECT x\u0301CREATE TRIGGER FROM docs;",
        "SELECT CREATE TRIGGER$label FROM docs;",
        "SELECT CREATE TRIGGER\u0301 FROM docs;",
        "SELECT CREATE TRİGGER FROM docs;",
        "SELECT x$ALTER TRIGGER FROM docs;",
        "SELECT x\u0301ALTER TRIGGER FROM docs;",
        "SELECT ALTER TRIGGER$label FROM docs;",
        "SELECT ALTER TRIGGER\u0301 FROM docs;",
    ],
)
def test_identifier_parts_are_not_trigger_keywords(source: str) -> None:
    assert _check(source) == []


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TRIGGER audit AFTER INSERT ON calls EXECUTE FUNCTION audit();",
        "ALTER EVENT TRIGGER ddl_audit RENAME TO next_audit;",
    ],
)
def test_copy_input_is_not_executable_trigger_ddl(ddl: str) -> None:
    source = f"COPY seed(body) FROM STDIN;\n{ddl}\n\\.\n{ddl}"
    assert _check(source) == []
    assert len(_check(f"{ddl}\n{source}")) == 1
