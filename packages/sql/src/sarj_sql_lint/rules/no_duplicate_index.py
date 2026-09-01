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
from sarj_sql_lint.rules._index_analysis import IndexDefinition, IndexSignature, authored_indexes


if TYPE_CHECKING:
    from pathlib import Path


@final
class NoDuplicateIndex(Rule):
    id = "no-duplicate-index"
    code = "SARJ117"
    documentation = RuleDocumentation(
        summary="Disallow structurally duplicate indexes on the same table.",
        rationale=(
            "Equivalent indexes duplicate write amplification, storage, vacuum work, and planner choices without serving a distinct lookup."
        ),
        remediation="Remove the later index or change its keys, order, operator classes, included columns, or predicate to serve a distinct read path.",
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only authored migrations are checked; dumps, fixtures, and recognized generator-owned migrations are excluded.",
            "Comparison is within one file and includes table, access method, ordered key expressions and operator classes, INCLUDE columns, and WHERE predicate.",
            "Semantically equivalent expressions with different source spelling are intentionally not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="duplicate-index-shape",
                title="Two differently named indexes have the same structure",
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
                title="Partial indexes with different predicates remain distinct",
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
        first_by_signature: dict[IndexSignature, IndexDefinition] = {}
        findings: list[Diagnostic] = []
        for index in authored_indexes(path, source):
            first = first_by_signature.setdefault(index.signature, index)
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
