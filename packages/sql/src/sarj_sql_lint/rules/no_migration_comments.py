from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    POSTGRES_IDENTIFIER_CONTINUATION,
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    SourceComment,
    is_dump_file,
    is_generated_migration,
    is_migration_source,
    mask_sql,
    mask_sql_comments,
    redirect_to_model,
    source_location,
    sql_comments,
)
from sarj_sql_lint.rules._copy_input import sql_before_copy_input


if TYPE_CHECKING:
    from pathlib import Path


_RUNNER_DIRECTIVE = re.compile(
    r"(?:migrate:(?:up|down)(?:[ \t]+transaction:(?:true|false))?|"
    r"\+goose[ \t]+(?:Up|Down|StatementBegin|StatementEnd|NO[ \t]+TRANSACTION|ENVSUB[ \t]+(?:ON|OFF))|"
    r"\+migrate[ \t]+(?:Up|Down|StatementBegin|StatementEnd)(?:[ \t]+notransaction)?|"
    r"liquibase[ \t]+formatted[ \t]+sql|"
    r"changeset[ \t]+[^\s:]+:[^\s:]+(?:[ \t]+[A-Za-z][A-Za-z0-9_-]*:[^\s]+)*|"
    r"rollback[ \t]+(?:ALTER|CREATE|DELETE|DROP|INSERT|UPDATE|TRUNCATE|SELECT|DO|SET|GRANT|REVOKE)\b[^\n]*|"
    r"(?:sql-)?dialect[ \t]*:[ \t]*(?:postgres(?:ql)?|sqlite|mysql|mariadb|clickhouse)|"
    r"atlas:txmode[ \t]+(?:file|none)|> statement-breakpoint)",
    re.IGNORECASE,
)
_COMMENT_ON = re.compile(
    rf"(?<!{POSTGRES_IDENTIFIER_CONTINUATION})(?ai:COMMENT)[ \t\r\n\f\v]+(?ai:ON)(?!{POSTGRES_IDENTIFIER_CONTINUATION})"
)
_COMMENT_IS = re.compile(rf"(?<!{POSTGRES_IDENTIFIER_CONTINUATION})(?ai:IS)(?!{POSTGRES_IDENTIFIER_CONTINUATION})")
_COMMENT_REMOVAL_VALUE = re.compile(
    r"(?:(?ai:NULL|E'')|''|(?P<tag>\$(?:[A-Za-z_\u0080-\U0010ffff][A-Za-z0-9_\u0080-\U0010ffff]*)?\$)(?P=tag))"
)


@final
class NoMigrationComments(Rule):
    id = "no-migration-comments"
    code = "SARJ128"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Encode migration invariants in SQL instead of explanatory comments.",
        rationale=(
            "Comments that describe bounds or allowed states leave those invariants unenforced, while SQL CHECK, "
            "NOT NULL, UNIQUE and foreign-key constraints reject invalid writes from every caller."
        ),
        remediation=(
            "Express data invariants with SQL constraints and delete explanatory line/block comments and COMMENT ON "
            "statements that store prose. COMMENT ON with NULL or an empty string may remove existing comments. "
            "Put deployment context in the change description. Retain only executable runner, dialect, "
            "and statement-boundary directives. Migration sarj-noqa comments are also reported."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.SAFE,
        limitations=(
            "Checks authored and generated migrations; schema dumps and non-migration SQL are excluded.",
            "Exact standalone dbmate, Goose, sql-migrate, Liquibase, Atlas, dialect and Drizzle breakpoint directives are preserved.",
            "PostgreSQL line and nested block comments are recognized; MySQL # comments are outside the shared scanner.",
            "Strings and quoted identifiers are not comments, including scalar dollar-quoted data. Comments in executable bodies are checked.",
            "COMMENT ON cleanup using unquoted NULL or an empty plain, escape, or dollar-quoted string is allowed; quoted NULL and nonempty strings still store comments.",
            "Analysis stops before top-level COPY FROM STDIN; payloads and following commands are not inferred.",
            "Conditional safe fixes reuse the existing banner and complete supported disabled-SQL line-comment profiles only when both rules report the same location. Arbitrary prose, declared ranges, COMMENT ON statements, directives, references, rollback guidance, suppression and license comments remain manual.",
            "Safe fixes preserve physical newlines and refuse COPY input, dollar-quoted data and procedural sources. Direct source-string fixes refuse a visible BOM prefix; file fixes preserve the original UTF-8 BOM through the shared file adapter. Generated migrations remain model-owned. No constraint is invented from prose.",
        ),
        examples=(
            RuleExample(
                example_id="inert-disabled-statement",
                scenario="inert-comment",
                title="Remove a proven disabled statement without changing executable SQL",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.sql("migrations/001.sql", "-- DROP TABLE legacy;\nSELECT 1;\n"),),
                fixed_files=(ExampleFile.sql("migrations/001.sql", "\nSELECT 1;\n"),),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="inert-disabled-statement-fixed",
                scenario="inert-comment",
                title="Executable SQL remains after removing the inert comment",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.sql("migrations/001.sql", "\nSELECT 1;\n"),),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="comment-only-range",
                title="A comment cannot enforce a column range",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001.sql",
                        "CREATE TABLE IF NOT EXISTS settings (retries INTEGER); -- retries must be positive\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/001.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="enforced-range",
                title="SQL enforces the bound while runner directives remain executable",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001.sql",
                        "-- migrate:up\nCREATE TABLE IF NOT EXISTS settings (retries INTEGER CHECK (retries > 0));\n"
                        "-- migrate:down\nDROP TABLE IF EXISTS settings;\n",
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
        source = sql_before_copy_input(source)
        if is_dump_file(source, path) or not is_migration_source(path, source):
            return []
        lines = source.splitlines()
        findings = [
            Diagnostic(
                path,
                comment.line,
                comment.column,
                self.code,
                "Migration comment is not an executable tool directive; encode invariants in SQL constraints "
                "and move deployment context to the change description.",
            )
            for comment in sql_comments(source, mask_dollar_literals=True)
            if not _is_tool_directive(comment, lines)
        ]
        masked = mask_sql(source, mask_dollar_literals=True)
        comment_statements = tuple(_COMMENT_ON.finditer(masked))
        uncommented = mask_sql_comments(source) if comment_statements else source
        for match in comment_statements:
            if _removes_existing_comment(masked, uncommented, match.end()):
                continue
            line, column = source_location(source, match.start())
            findings.append(
                Diagnostic(
                    path,
                    line,
                    column,
                    self.code,
                    "COMMENT ON stores prose instead of enforcing an invariant; use SQL constraints "
                    "and keep deployment context in the change description.",
                )
            )
        return redirect_to_model(findings, model_owned=is_generated_migration(path, source))


def _is_tool_directive(comment: SourceComment, lines: list[str]) -> bool:
    return (
        not comment.block
        and not lines[comment.line - 1][: comment.column - 1].strip()
        and _RUNNER_DIRECTIVE.fullmatch(comment.body) is not None
    )


def _removes_existing_comment(masked: str, uncommented: str, start: int) -> bool:
    end = masked.find(";", start)
    if end < 0:
        end = len(masked)
    separators = tuple(_COMMENT_IS.finditer(masked, start, end))
    if not separators:
        return False
    value = uncommented[separators[-1].end() : end].strip()
    return _COMMENT_REMOVAL_VALUE.fullmatch(value) is not None
