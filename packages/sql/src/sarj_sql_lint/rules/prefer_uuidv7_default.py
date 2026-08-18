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
    mask_sql,
    redirect_to_model,
)


if TYPE_CHECKING:
    from pathlib import Path


PATTERN = re.compile(r"\bgen_random_uuid\s*\(", re.IGNORECASE)

_MESSAGE = (
    "`gen_random_uuid()` generates a random UUIDv4 — use `uuidv7()` (Postgres 18). "
    "Random keys scatter inserts across every B-tree leaf page; UUIDv7 is "
    "time-ordered, so inserts append to the index's right edge."
)


@final
class PreferUuidv7Default(Rule):
    id = "prefer-uuidv7-default"
    code = "SARJ109"
    documentation = RuleDocumentation(
        summary="`gen_random_uuid()` emits a random UUIDv4 — use `uuidv7()` so keys are time-ordered.",
        rationale="Random UUID keys scatter inserts across a B-tree, while time-ordered UUIDv7 values preserve index locality.",
        remediation="Use the PostgreSQL uuidv7() function for generated UUID defaults and values.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=("uuidv7() requires PostgreSQL 18 or an equivalent extension-provided function.",),
        examples=(
            RuleExample(
                example_id="random-uuid-default",
                title="Random UUID default",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_calls.sql",
                        "CREATE TABLE call (id UUID PRIMARY KEY DEFAULT gen_random_uuid());\n",  # sarj-noqa: SARJ053 -- documented rejected example
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_calls.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="time-ordered-uuid-default",
                title="Time-ordered UUID default",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/001_calls.sql", "CREATE TABLE call (id UUID PRIMARY KEY DEFAULT uuidv7());\n"
                    ),
                ),
                focus_path=PurePosixPath("migrations/001_calls.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if is_dump_file(source, path):
            return []
        model_owned = is_generated_migration(path, source)
        return redirect_to_model(
            [
                Diagnostic(
                    path=path,
                    line=lineno,
                    col=match.start() + 1,
                    code=self.code,
                    message=_MESSAGE,
                )
                for lineno, line in enumerate(mask_sql(source).splitlines(), start=1)
                for match in PATTERN.finditer(line)
            ],
            model_owned=model_owned,
        )
