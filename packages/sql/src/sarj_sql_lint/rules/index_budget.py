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
from sarj_sql_lint.rules._index_analysis import IndexDefinition, IndexSignature, authored_indexes, index_namespace_key


if TYPE_CHECKING:
    from pathlib import Path


_MIGRATION_INDEX_LIMIT = 8
_TABLE_INDEX_LIMIT = 3


@final
class IndexBudget(Rule):
    id = "excess-migration-index-requires-justification"
    code = "SARJ116"
    documentation = RuleDocumentation(
        summary="Require a structured local justification for excess explicit indexes in an authored migration.",
        rationale=(
            "Every explicit index adds write amplification, storage, vacuum work, and planner surface; bursts of indexes "
            "often encode unmeasured read paths in the transactional database."
        ),
        remediation=(
            "Keep at most three explicit indexes per table and eight per migration, or place an exact "
            "`index-justification: app-read: ...; evidence: URL`/`ticket: ABC-123` or "
            "`index-justification: referential-action: ...` comment immediately above each excess index. "
            "For `CREATE UNIQUE INDEX` only, `index-justification: uniqueness-constraint: ...; ticket: ABC-123` "
            "is also accepted."
        ),
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        aliases=("index-budget",),
        limitations=(
            "Only authored production migrations are checked; tests, dumps, fixtures, and recognized generator-owned migrations are excluded.",
            "Duplicate index shapes and same-name replacement statements do not consume this budget; SARJ117 reports structural duplicates.",
            "Index declarations inside dollar-quoted stored or anonymous program bodies are not inferred.",
            "The warning budgets distinct explicit index definitions in one file; it does not estimate workload selectivity or fleet-wide index count.",
        ),
        examples=(
            RuleExample(
                example_id="unjustified-index-burst",
                title="A fourth explicit index has no local justification",
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
                example_id="justified-index-burst",
                title="An excess index names its application read and durable ticket",
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
        indexes = authored_indexes(path, source)
        table_positions: Counter[str] = Counter()
        findings: list[Diagnostic] = []
        seen_names: set[str] = set()
        seen_signatures: set[IndexSignature] = set()
        distinct_indexes: list[IndexDefinition] = []
        for index in indexes:
            namespace_key = index_namespace_key(index)
            has_reused_name = namespace_key is not None and namespace_key in seen_names
            if has_reused_name or index.signature in seen_signatures:
                continue
            if namespace_key is not None:
                seen_names.add(namespace_key)
            seen_signatures.add(index.signature)
            distinct_indexes.append(index)
        for total_position, index in enumerate(distinct_indexes, start=1):
            table_positions[index.table] += 1
            exceeds_total = total_position > _MIGRATION_INDEX_LIMIT
            exceeds_table = table_positions[index.table] > _TABLE_INDEX_LIMIT
            if not (exceeds_total or exceeds_table) or index.justified:
                continue
            limits: list[str] = []
            if exceeds_table:
                limits.append(f"Index {table_positions[index.table]} for table `{index.table}` exceeds limit 3")
            if exceeds_total:
                lead = "distinct" if limits else "Distinct"
                limits.append(f"{lead} index {total_position} in this migration exceeds limit 8")
            accepted_kinds = "app-read or referential-action"
            if index.unique:
                accepted_kinds += ", or uniqueness-constraint"
            findings.append(
                Diagnostic(
                    path,
                    index.line,
                    index.column,
                    self.code,
                    "; ".join(limits)
                    + f". Remove the index or immediately precede it with an exact {accepted_kinds} justification.",
                )
            )
        return findings
