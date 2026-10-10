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
    mask_sql,
    redirect_to_model,
    source_location,
)


if TYPE_CHECKING:
    from pathlib import Path


# Match TIMESTAMP unless followed by WITH TIME ZONE, allowing an optional (n) precision modifier.
PATTERN = re.compile(
    r"\bTIMESTAMP\b(?!\s*(?:\(\s*\d+\s*\)\s*)?WITH\s+TIME\s+ZONE\b)",
    re.IGNORECASE,
)

_OPENS_LIST_ITEM = frozenset("(,")
_CLOSES_LIST_ITEM = frozenset(",)")


def _is_column_reference(source: str, start: int, end: int) -> bool:
    before = start - 1
    while before >= 0 and source[before].isspace():
        before -= 1
    after = end
    while after < len(source) and source[after].isspace():
        after += 1
    return (
        before >= 0
        and source[before] in _OPENS_LIST_ITEM
        and after < len(source)
        and source[after] in _CLOSES_LIST_ITEM
    )


@final
class EnforceTimestamptz(Rule):
    id = "enforce-timestamptz"
    code = "SARJ101"
    documentation = RuleDocumentation(
        summary="TIMESTAMP without TIME ZONE — use TIMESTAMPTZ.",
        rationale="Naive timestamps discard offset context and make cross-time-zone comparisons ambiguous.",
        remediation="Declare persisted instants as TIMESTAMPTZ or TIMESTAMP WITH TIME ZONE.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        examples=(
            RuleExample(
                example_id="naive-created-at",
                title="Naive timestamp column",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_orders.sql",
                        "CREATE TABLE orders (created_at TIMESTAMP NOT NULL);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_orders.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="zoned-created-at",
                title="Timestamp with time-zone semantics",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_orders.sql",
                        "CREATE TABLE orders (created_at TIMESTAMPTZ NOT NULL);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_orders.sql"),
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

        diags: list[Diagnostic] = []
        masked = mask_sql(source, mask_dollar_literals=True)
        for match in PATTERN.finditer(masked):
            start = match.start()
            if _is_column_reference(masked, start, match.end()):
                continue
            location = source_location(source, start)
            diags.append(
                Diagnostic(
                    path=path,
                    line=location.line,
                    col=location.column,
                    code=self.code,
                    message=(
                        "Use `TIMESTAMPTZ` (or `TIMESTAMP WITH TIME ZONE`) — "
                        "naive TIMESTAMP discards offset and is rarely correct."
                    ),
                )
            )
        return redirect_to_model(diags, model_owned=model_owned)
