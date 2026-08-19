from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sarj_sql_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_dump_file,
    is_generated_migration,
    is_postgres_source,
    locate,
    mask_sql,
    redirect_to_model,
    split_statements,
)


if TYPE_CHECKING:
    from pathlib import Path


_CREATE_TRIGGER = re.compile(r"\bCREATE\s+(?:(?:OR\s+REPLACE|CONSTRAINT)\s+)?TRIGGER\b", re.IGNORECASE | re.DOTALL)


@final
class NoCreateTrigger(Rule):
    id = "no-create-trigger"
    code = "SARJ114"
    documentation = RuleDocumentation(
        summary="This project keeps database behavior explicit instead of introducing PostgreSQL triggers.",
        rationale=(
            "Under a single-writer application architecture, triggers hide writes and state transitions from "
            "engineers reading application code and make the behavior difficult to exercise through ordinary "
            "unit-test seams. Triggers may still be appropriate for approved multi-writer integrity or audit needs."
        ),
        remediation=(
            "Use a declarative database constraint where possible or explicit transactional application behavior; "
            "suppress this policy when an approved database-owned invariant requires a trigger."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "PostgreSQL CREATE TRIGGER and CREATE CONSTRAINT TRIGGER statements are reported.",
            "This is an organization-specific single-writer architecture policy, not a claim that triggers are invalid.",
            "Dump files and non-PostgreSQL dialects are excluded.",
            "Generated migrations report against their owning model when one can be identified.",
        ),
        examples=(
            RuleExample(
                example_id="postgres-trigger",
                title="Hidden trigger behavior",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001.sql",
                        "CREATE TRIGGER update_timestamp BEFORE UPDATE ON calls EXECUTE FUNCTION set_timestamp();\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="declarative-constraint",
                title="Declarative database invariant",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001.sql",
                        "ALTER TABLE child ADD CONSTRAINT child_tenant_fk "
                        "FOREIGN KEY (organization_id, parent_id) REFERENCES parent (organization_id, id);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path) or not is_postgres_source(path, source):
            return []
        model_owned = is_generated_migration(path, source)
        diagnostics: list[Diagnostic] = []
        for statement in split_statements(mask_sql(source)):
            text = "\n".join(fragment for _, fragment in statement)
            match = _CREATE_TRIGGER.search(text)
            if match is None:
                continue
            line, col = locate(statement, match.start())
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=line,
                    col=col,
                    code=self.code,
                    message=(
                        "Project architecture keeps database behavior explicit; use a declarative constraint or "
                        "transactional application behavior, or suppress for an approved database-owned invariant."
                    ),
                )
            )
        return redirect_to_model(diagnostics, model_owned=model_owned)
