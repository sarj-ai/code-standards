from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
)
from sarj_python_lint.rules._sql import is_store_module
from sarj_python_lint.rules._store_sql import relation_key, sql_child, store_queries
from sarj_python_lint.rules.store_insert_requires_on_conflict import StoreInsertRequiresOnConflict


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_BAD = """from psycopg import AsyncCursor
class RowsFixture:
    def __init__(self, cursor: AsyncCursor):
        self.cursor = cursor
    async def insert(self):
        await self.cursor.execute("INSERT INTO item(id) VALUES(%s)", (1,))
"""


@final
class StoreInsertRequiresExplicitConflictPolicy(Rule):
    id = "store-insert-requires-explicit-conflict-policy"
    code = "SARJ547"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Declare SQL conflict behavior for store INSERT statements, including fixture writes.",
        rationale="A visible SQL conflict policy makes retry and fixture behavior reviewable at the write boundary. Plain INSERT can intentionally reject duplicates; record that contract with an exact rule exception.",
        remediation="Declare the intended ON CONFLICT behavior, or add an exact SARJ547 exception explaining why duplicate rejection, append-only insertion, or deliberately invalid fixture data is required. Preserve uniqueness, errors, return shape and transaction behavior; DO NOTHING is not an automatic replacement.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks recovered INSERT statements reaching import-proven Psycopg execution in recognized store modules or class-owned persistence helpers, including test fixtures and direct same-class forwarding wrappers. Generated Python and unknown or dynamically composed SQL abstain.",
            "Any explicit PostgreSQL ON CONFLICT clause declares a policy. This rule does not prove its target, concurrency correctness, replay behavior or side effects. SELECT-side existence checks alone do not establish a concurrency-safe duplicate policy.",
            "Plain INSERT remains a review finding when Python handles UniqueViolation or a fixture comment states invalid-row intent; preserve those contracts with an explained exact exception.",
            "Replay-named store INSERT findings already owned by SARJ018 take precedence. This broader policy remains a warning and requires an explained exact exception for intentional database-error fixtures.",
        ),
        examples=(
            RuleExample(
                example_id="fixture-insert-policy",
                title="Fixture inserts need an explicit duplicate decision",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/fixtures/rows.py", _BAD),),
                focus_path=PurePosixPath("tests/fixtures/rows.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="fixture-declared-policy",
                title="A fixture declares its duplicate behavior",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/fixtures/rows.py", _BAD.replace("VALUES(%s)", "VALUES(%s) ON CONFLICT DO NOTHING")
                    ),
                ),
                focus_path=PurePosixPath("tests/fixtures/rows.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None or "INSERT" not in context.source.upper():
            return []
        from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- only native SQL INSERT candidates need parser types.

        replay_lines = {finding.line for finding in StoreInsertRequiresOnConflict().check_context(context)}
        findings: dict[tuple[int, int], Diagnostic] = {}
        for query in store_queries(context):
            if not isinstance(query.statement, exp.Insert) or query.statement.args.get("conflict") is not None:
                continue
            relation = sql_child(query.statement, "this")
            relation = sql_child(relation, "this") if isinstance(relation, exp.Schema) else relation
            if relation_key(relation) is None:
                continue
            if (not is_store_module(context.path) and query.owner is None) or query.node.lineno in replay_lines:
                continue
            node = query.node
            findings[node.lineno, node.col_offset] = Diagnostic(
                context.path,
                node.lineno,
                node.col_offset + 1,
                self.code,
                "This store INSERT has no ON CONFLICT clause; choose SQL conflict behavior or explain intentional duplicate failure or invalid fixture data in an exact SARJ547 exception. Preserve the original error and transaction contract.",
                severity=Severity.WARNING,
            )
        return sorted(findings.values(), key=lambda finding: (finding.line, finding.col))
