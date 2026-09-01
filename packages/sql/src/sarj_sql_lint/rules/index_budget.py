from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath
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
)
from sarj_sql_lint.rules._index_analysis import authored_secondary_indexes


if TYPE_CHECKING:
    from pathlib import Path


_MIGRATION_INDEX_LIMIT = 8
_TABLE_INDEX_LIMIT = 3


@final
class IndexBudget(Rule):
    id = "index-budget"
    code = "SARJ116"
    documentation = RuleDocumentation(
        summary="Limit secondary indexes in one authored migration unless each excess index has structured evidence.",
        rationale=(
            "Every secondary index adds write amplification, storage, vacuum work, and planner surface; bursts of indexes "
            "often encode unmeasured read paths in the transactional database."
        ),
        remediation=(
            "Keep at most three secondary indexes per table and eight per migration, or place an exact "
            "`index-justification: app-read: ...; evidence: URL`/`ticket: ABC-123` or "
            "`index-justification: referential-action: ...` comment immediately above each excess index."
        ),
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only authored migrations are checked; dumps, fixtures, and recognized generator-owned migrations are excluded.",
            "CREATE UNIQUE INDEX is excluded because it may back a uniqueness constraint.",
            "The warning budgets index statements in one file; it does not estimate workload selectivity or fleet-wide index count.",
        ),
        examples=(
            RuleExample(
                example_id="unjustified-index-burst",
                title="A fourth secondary index has no read-path evidence",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/004_indexes.sql",
                        "CREATE INDEX a_idx ON event(a);\nCREATE INDEX b_idx ON event(b);\n"
                        "CREATE INDEX c_idx ON event(c);\nCREATE INDEX d_idx ON event(d);\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/004_indexes.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="measured-index-burst",
                title="An excess application-read index carries durable evidence",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/004_indexes.sql",
                        "CREATE INDEX a_idx ON event(a);\nCREATE INDEX b_idx ON event(b);\n"
                        "CREATE INDEX c_idx ON event(c);\n"
                        "-- index-justification: app-read: event delivery queue; ticket: APP-812\n"
                        "CREATE INDEX d_idx ON event(d);\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/004_indexes.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        indexes = authored_secondary_indexes(path, source)
        table_positions: Counter[str] = Counter()
        findings: list[Diagnostic] = []
        for total_position, index in enumerate(indexes, start=1):
            table_positions[index.table] += 1
            exceeds_total = total_position > _MIGRATION_INDEX_LIMIT
            exceeds_table = table_positions[index.table] > _TABLE_INDEX_LIMIT
            if not (exceeds_total or exceeds_table) or index.justified:
                continue
            limits: list[str] = []
            if exceeds_table:
                limits.append(f"three for table `{index.table}`")
            if exceeds_total:
                limits.append("eight in one migration")
            findings.append(
                Diagnostic(
                    path,
                    index.line,
                    index.column,
                    self.code,
                    "Secondary-index budget exceeded ("
                    + " and ".join(limits)
                    + "). Remove the index or add an exact local app-read or referential-action justification.",
                )
            )
        return findings
