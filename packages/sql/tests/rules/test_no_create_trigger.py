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
    ],
)
def test_reports_postgres_trigger_creation(source: str) -> None:
    findings = _check(source)
    assert len(findings) == 1
    assert findings[0].code == "SARJ114"


@pytest.mark.parametrize(
    "source",
    [
        "-- CREATE TRIGGER is intentionally forbidden",
        "INSERT INTO docs(body) VALUES ('CREATE TRIGGER example');",
        "DROP TRIGGER IF EXISTS update_timestamp ON calls;",
        "CREATE TABLE trigger_audit (id uuid PRIMARY KEY);",
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
