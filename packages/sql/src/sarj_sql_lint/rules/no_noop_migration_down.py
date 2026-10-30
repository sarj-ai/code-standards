from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from sarj_sql_lint._postgres import parse_postgres
from sarj_sql_lint.rule_base import (
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    dollar_quoted_spans,
    is_dump_file,
    is_generated_migration,
    is_migration_source,
    mask_sql,
    redirect_to_model,
    sql_comments,
)


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


_SECTION = re.compile(r"(?:migrate:|\+(?:goose|migrate)[ \t]+)(up|down)\b", re.IGNORECASE)
_EMPTY_DO = re.compile(
    r"\bDO\s+(?:LANGUAGE\s+plpgsql\s+)?BEGIN\s*(?:NULL\s*;\s*)*END\s*"
    r"(?:LANGUAGE\s+plpgsql\s*)?;",
    re.IGNORECASE,
)
_DOWN_FILE = re.compile(r"(?:^|[._-])down\.sql$", re.IGNORECASE)
type _SqlArgument = exp.Expr | list[exp.Expr] | str | int | float | bool | None


@final
class NoNoopMigrationDown(Rule):
    id = "no-noop-migration-down"
    code = "SARJ127"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="A migration down section must perform a rollback instead of silently doing nothing.",
        rationale=(
            "An empty or SELECT 1 rollback can be recorded as successfully reverted while its schema and data "
            "changes remain installed, leaving the migration ledger inconsistent with the database."
        ),
        remediation=(
            "Implement the inverse schema/data change using guarded DDL. If reversal cannot be supported, fail "
            "explicitly with an exception instead of recording a successful no-op rollback."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Checks explicit dbmate, Goose and sql-migrate down sections and conventional .down.sql files; forward-only migration formats are not required to add down sections.",
            "Reports only empty bodies, literal-only SELECT statements, session settings, transaction delimiters and empty PL/pgSQL DO blocks, or combinations of these.",
            "Calls, queries reading relations, dynamic SQL, malformed SQL and nonempty procedural blocks are preserved; inverse correctness is not inferred.",
            "SQL strings and comments cannot introduce a down section. Schema dumps and non-migration SQL are excluded.",
        ),
        examples=(
            RuleExample(
                example_id="literal-only-rollback",
                title="A successful SELECT leaves the created table installed",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001.sql",
                        "-- migrate:up\nCREATE TABLE IF NOT EXISTS work (id UUID PRIMARY KEY);\n"
                        "-- migrate:down\nSELECT 1;\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="inverse-schema-change",
                title="The rollback reverses the schema change",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001.sql",
                        "-- migrate:up\nCREATE TABLE IF NOT EXISTS work (id UUID PRIMARY KEY);\n"
                        "-- migrate:down\nDROP TABLE IF EXISTS work;\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path) or not is_migration_source(path, source):
            return []
        findings = [
            Diagnostic(
                path,
                line,
                1,
                self.code,
                "Down migration contains only no-op statements; reverse the schema/data change or raise an "
                "explicit error when rollback is unsupported.",
            )
            for line, body in _down_sections(path, source)
            if _is_noop(body)
        ]
        return redirect_to_model(findings, model_owned=is_generated_migration(path, source))


def _down_sections(path: Path, source: str) -> list[tuple[int, str]]:
    lines = source.splitlines(keepends=True)
    body_lines = {
        line
        for start, end in dollar_quoted_spans(source)
        for line in range(source.count("\n", 0, start) + 1, source.count("\n", 0, max(start, end - 1)) + 2)
    }
    boundaries = [
        (comment.line, match.group(1).lower())
        for comment in sql_comments(source, mask_dollar_literals=True)
        if not comment.block
        and comment.line not in body_lines
        and not lines[comment.line - 1][: comment.column - 1].strip()
        and (match := _SECTION.match(comment.body)) is not None
    ]
    sections = [
        (line, "".join(lines[line : boundaries[index + 1][0] - 1 if index + 1 < len(boundaries) else None]))
        for index, (line, section) in enumerate(boundaries)
        if section == "down"
    ]
    if not boundaries and _DOWN_FILE.search(path.name) is not None:
        sections.append((1, source))
    return sections


def _is_noop(source: str) -> bool:
    masked = mask_sql(source, mask_dollar_literals=True)
    chars = list(source)
    for match in _EMPTY_DO.finditer(masked):
        chars[match.start() : match.end()] = ("\n" if char == "\n" else " " for char in match.group())
    try:
        statements = parse_postgres("".join(chars))
    except ParseError, TokenError:
        return False
    return all(statement is None or _is_noop_statement(statement) for statement in statements)


def _is_noop_statement(statement: exp.Expr) -> bool:
    if isinstance(statement, (exp.Set, exp.Transaction, exp.Commit, exp.Rollback)):
        return True
    arguments: Mapping[str, _SqlArgument] = statement.args
    if isinstance(statement, exp.Select):
        return _is_noop_select(arguments, statement.expressions)
    command = arguments.get("this")
    return isinstance(statement, exp.Command) and isinstance(command, str) and command.upper() == "RESET"


def _is_noop_select(arguments: Mapping[str, _SqlArgument], expressions: Sequence[exp.Expr]) -> bool:
    if any(value for name, value in arguments.items() if name != "expressions"):
        return False
    return bool(expressions) and all(_is_literal(item) for item in expressions)


def _is_literal(expression: exp.Expr) -> bool:
    if isinstance(expression, (exp.Literal, exp.Boolean, exp.Null)):
        return True
    if isinstance(expression, (exp.Alias, exp.Paren, exp.Neg)):
        arguments: Mapping[str, _SqlArgument] = expression.args
        inner = arguments.get("this")
        return isinstance(inner, exp.Expr) and _is_literal(inner)
    return False
