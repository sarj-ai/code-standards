from __future__ import annotations

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
from sarj_sql_lint.rules._index_analysis import (
    IndexDefinition,
    IndexDrop,
    IndexSignature,
    authored_index_operations,
    drop_namespace_keys,
    index_namespace_key,
)


if TYPE_CHECKING:
    from pathlib import Path


@final
class NoDuplicateIndex(Rule):
    id = "no-duplicate-index"
    code = "SARJ117"
    documentation = RuleDocumentation(
        summary="Report repeated normalized index definitions that remain active in one authored migration.",
        rationale=(
            "Two explicit indexes with the same normalized structural definition add duplicate write amplification, "
            "storage, vacuum work, and planner choices in the migration's resulting state."
        ),
        remediation=(
            "Remove the repeated definition, or explicitly drop the superseded index in the same migration. If both "
            "indexes must remain, give them a materially different key, uniqueness or partition scope, access method, "
            "included columns, null treatment, predicate, tablespace, or storage parameters."
        ),
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only explicit indexes in one authored production migration are checked; tests, dumps, fixtures, recognized generator-owned migrations, and indexes that exist only outside the file are excluded.",
            "DROP INDEX operations in the same migration remove the named definition from the final active set before repeated definitions are compared.",
            "The normalized definition includes uniqueness, table and ONLY scope, access method, ordered key expressions and operator classes, INCLUDE columns, NULLS DISTINCT treatment, storage parameters, tablespace, and WHERE predicate.",
            "Semantically equivalent expressions with different normalized source spelling are intentionally not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="duplicate-index-shape",
                title="Two active indexes repeat the same normalized definition",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/002_indexes.sql",
                        "CREATE INDEX event_owner_a ON event(owner_id DESC);\n"
                        "CREATE INDEX event_owner_b ON event ( owner_id DESC );\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/002_indexes.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="distinct-index-predicates",
                title="Different partial-index predicates remain distinct",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/002_indexes.sql",
                        "CREATE INDEX event_open ON event(owner_id) WHERE status = 'open';\n"
                        "CREATE INDEX event_closed ON event(owner_id) WHERE status = 'closed';\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/002_indexes.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        active: dict[str, IndexDefinition] = {}
        for operation in authored_index_operations(path, source):
            if isinstance(operation, IndexDrop):
                for key in drop_namespace_keys(operation, set(active)):
                    del active[key]
                continue
            index = operation
            key = index_namespace_key(index) or f"<unnamed>@{index.start}"
            active.setdefault(key, index)
        findings: list[Diagnostic] = []
        seen: dict[IndexSignature, IndexDefinition] = {}
        for index in sorted(active.values(), key=lambda definition: definition.start):
            first = seen.setdefault(index.signature, index)
            if first is index:
                continue
            findings.append(
                Diagnostic(
                    path,
                    index.line,
                    index.column,
                    self.code,
                    f"Index `{index.name}` duplicates `{first.name}` on table `{index.table}`; remove the later index.",
                )
            )
        return findings
