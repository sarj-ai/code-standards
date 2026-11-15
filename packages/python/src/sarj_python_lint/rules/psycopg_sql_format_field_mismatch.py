from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, Final, final, override

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
from sarj_python_lint.sql_literals import SQLFormatFault, SQLFormatMismatch, sql_format_mismatches


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_LITERAL_BRACES: Final = "if the braces are SQL text, write them as {{ and }}"


@final
class PsycopgSqlFormatFieldMismatch(Rule):
    id = "psycopg-sql-format-field-mismatch"
    code = "SARJ576"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Give psycopg SQL.format an argument for every replacement field.",
        rationale=(
            "psycopg SQL.format reads every unescaped brace in the template as a replacement field and raises on "
            "the first field it cannot fill: IndexError for a missing positional argument, KeyError for a missing "
            "keyword, and ValueError for unmatched braces, format specs, conversions, or mixed automatic and "
            "numbered fields. The call fails every time it runs. Braces that belong to the SQL text, such as an "
            "empty JSON object '{}', are the usual cause. Ruff F521-F525 check str.format literals only."
        ),
        remediation=(
            "Write braces that belong to the SQL text as {{ and }}. For a real field, pass the missing positional "
            "or keyword argument, use one numbering style, and drop format specs and conversions."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Checks templates that resolve statically: string literals, implicitly concatenated literals, "
                "constant bindings and + compositions passed to psycopg.sql.SQL."
            ),
            (
                "SQL must be import-proven by the shared provenance analysis, which currently abstains inside "
                "comprehensions and in files that use SQL as a type argument, such as list[SQL]."
            ),
            "Calls with *args or **kwargs are skipped because their arguments are unknown.",
            "Extra positional and keyword arguments pass, matching psycopg.",
            "Each call reports the first field that fails, which is where psycopg raises.",
        ),
        examples=(
            RuleExample(
                example_id="sql-empty-object-literal",
                title="An empty JSON object in SQL text is read as a positional field",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/report.py",
                        "from psycopg.sql import SQL\n"
                        "def report_query(where):\n"
                        "    return SQL(\"SELECT COALESCE(data, '{}') FROM calls {where}\").format(where=where)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/report.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="missing-keyword-through-module-alias",
                title="A named field has no keyword argument",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/report.py",
                        "from psycopg import sql\n"
                        "def report_query(table):\n"
                        "    return sql.SQL('SELECT * FROM {table} {where}').format(table=table)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/report.py"),
                expected_count=1,
                public=True,
                scenario="missing-keyword",
            ),
            RuleExample(
                example_id="escaped-empty-object-literal",
                title="Escaped braces stay SQL text",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/report.py",
                        "from psycopg.sql import SQL\n"
                        "def report_query(where):\n"
                        "    return SQL(\"SELECT COALESCE(data, '{{}}') FROM calls {where}\").format(where=where)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/report.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="every-keyword-supplied",
                title="Every named field has a keyword argument",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/report.py",
                        "from psycopg import sql\n"
                        "def report_query(table, where):\n"
                        "    return sql.SQL('SELECT * FROM {table} {where}').format(table=table, where=where)\n",
                    ),
                ),
                focus_path=PurePosixPath("app/report.py"),
                expected_count=0,
                public=True,
                scenario="missing-keyword",
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None:
            return []
        return [
            Diagnostic(
                path=context.path,
                line=call.lineno,
                col=call.col_offset + 1,
                code=self.code,
                message=_message(mismatch),
                severity=Severity.ERROR,
            )
            for call, mismatch in sql_format_mismatches(context)
            if not context.suppressions.is_suppressed(call.lineno, self.code)
        ]


def _message(mismatch: SQLFormatMismatch) -> str:
    field = mismatch.field
    match mismatch.fault:
        case SQLFormatFault.UNBALANCED_BRACE:
            return f"psycopg SQL.format raises ValueError: the template has an unmatched brace; {_LITERAL_BRACES}."
        case SQLFormatFault.MODIFIER:
            return (
                f"psycopg SQL.format raises ValueError: field {field} has a format spec or conversion, which SQL "
                f"templates reject. Remove it, or {_LITERAL_BRACES}."
            )
        case SQLFormatFault.MIXED_NUMBERING:
            return (
                f"psycopg SQL.format raises ValueError: field {field} mixes automatic {{}} and numbered {{0}} "
                "fields. Use one numbering style."
            )
        case SQLFormatFault.MISSING_POSITIONAL:
            return (
                f"psycopg SQL.format raises IndexError: field {field} has no positional argument. Pass one, or "
                f"{_LITERAL_BRACES}."
            )
        case SQLFormatFault.MISSING_KEYWORD:
            return (
                f"psycopg SQL.format raises KeyError: field {field} has no keyword argument. Pass it by name, or "
                f"{_LITERAL_BRACES}."
            )
