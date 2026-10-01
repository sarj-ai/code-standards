from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, final, override

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
    is_suppressed,
)
from sarj_python_lint.rules._sql import sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_DATABASE_BEHAVIOR = re.compile(
    r"(?:\A|;)\s*(?:CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|TRIGGER)|"
    r"CREATE\s+CONSTRAINT\s+TRIGGER|ALTER\s+TABLE\s+[^;]+?\s+ENABLE\s+(?:(?:ALWAYS|REPLICA)\s+)?TRIGGER)\b",
    re.IGNORECASE,
)
_BAD = 'await conn.execute("CREATE TRIGGER fail_counter BEFORE UPDATE ON batch EXECUTE FUNCTION fail_counter()")\n'
_GOOD = 'await conn.execute("ALTER TABLE batch ADD CONSTRAINT fail_counter CHECK (false) NOT VALID")\n'


@final
class NoDatabaseProgrammability(Rule):
    id = "no-database-programmability"
    code = "SARJ470"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Keep stored SQL functions and triggers out of embedded SQL.",
        rationale="SQL hidden in Python can bypass migration-only architecture rules. Procedural fault fixtures require extra database objects and cleanup when a declarative constraint suffices.",
        remediation="Use declarative constraints or explicit transactional application behavior, including in test fixtures. Use an exact SARJ470 suppression for an approved compatibility exception.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks inline execute/executemany SQL and import-proven psycopg.sql.SQL constructors, including aliases, concatenation, f-strings, and format calls. Test fixtures are included; generated Python is excluded.",
            "Reports CREATE FUNCTION, CREATE OR REPLACE FUNCTION, CREATE TRIGGER, CREATE CONSTRAINT TRIGGER, and ALTER TABLE ENABLE TRIGGER. Existing function calls, DROP, and DISABLE remain valid.",
            "SQL comments, quoted values, and dollar-quoted bodies are masked. Standalone example strings and Python functions are not SQL execution.",
            "Runtime builders, SQL passed through named variables without SQL constructors, and dynamically generated DDL inside procedural bodies are not inferred. Non-PostgreSQL execution APIs are not distinguished.",
        ),
        examples=(
            RuleExample(
                example_id="trigger-fault",
                title="Procedural fault fixture",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("tests/fakes/batch_fault.py", _BAD),),
                focus_path=PurePosixPath("tests/fakes/batch_fault.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="constraint-fault",
                title="Declarative failure in a disposable database",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("tests/fakes/batch_fault.py", _GOOD),),
                focus_path=PurePosixPath("tests/fakes/batch_fault.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None:
            return []
        diagnostics: list[Diagnostic] = []
        for node in context.nodes(ast.Call):
            query = _query_expression(node, context)
            value = _literal_sql(query) if query is not None else None
            if value is None or _DATABASE_BEHAVIOR.search(strip_sql_noise(value)) is None:
                continue
            if is_suppressed(context.source_lines, node.lineno, self.code):
                continue
            diagnostics.append(
                Diagnostic(
                    path=context.path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.ERROR,
                    message="Stored SQL functions and triggers are prohibited by project architecture, including in test fixtures; use a declarative constraint or explicit transactional application code.",
                )
            )
        return sorted(diagnostics, key=lambda item: (item.line, item.col))


def _query_expression(node: ast.Call, context: PythonFileContext) -> ast.expr | None:
    if context.imports.resolves(node.func, sources=frozenset({"psycopg.sql"}), symbol="SQL") or (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == "SQL"
        and context.imports.resolves(node.func.value, sources=frozenset({"psycopg"}), symbol="sql")
    ):
        return node.args[0] if node.args else None
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in {"execute", "executemany"}:
        return None
    if node.args:
        return node.args[0]
    return next((keyword.value for keyword in node.keywords if keyword.arg == "query"), None)


def _literal_sql(node: ast.expr) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        return _literal_sql(node.func.value)
    return sql_string_value(node)
