from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._store_sql import relation_key, sql_child, sql_children, store_queries


if TYPE_CHECKING:
    from sqlglot import exp
    from sqlglot.optimizer.scope import Scope

    from sarj_python_lint._file_context import PythonFileContext


_BAD = """from psycopg import AsyncCursor
async def load(cursor: AsyncCursor):
    await cursor.execute('SELECT s.id, u.email FROM scenario s LEFT JOIN "user" u ON u.id = s.actor_id WHERE s.id = %s', (1,))
"""


@final
class PreferApplicationModelJoins(Rule):
    id = "prefer-application-model-joins"
    code = "SARJ545"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Compose distinct model records in application code instead of a cross-model SQL join.",
        rationale=(
            "A SQL join across separate persistence relations couples their read representations and can bypass "
            "the owning store's access and conversion policy. This architecture prefers bounded store reads and "
            "typed application composition when their consistency contract permits it."
        ),
        remediation=(
            "Review the relation owners, then load the related records through their typed stores, batch by IDs "
            "and compose them in application code. Preserve tenant filters, null-extension, cardinality, snapshot "
            "consistency, authorization and FOR UPDATE locks. Keep an explained exception for an atomic database "
            "operation; replacing a join with unrelated reads can change behavior or introduce N+1 queries."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "An architecture review warning, not a claim that SQL joins are inherently incorrect or slow. Distinct literal PostgreSQL relations are a source-visible proxy for ownership; syntax cannot establish whether two relations represent the same domain model.",
            "Checks native Psycopg execution and direct same-class query-forwarding wrappers in non-test Python. Each SELECT block needs at least two different direct table relations joined in that block. Self joins, CTE references, derived relations, table-valued functions, dynamic relation names, schema-ambiguous qualification and unsupported SQL abstain.",
            "Ordinary explicit JOINs, comma joins and lateral modifiers over direct relations remain reviewable. A join to a CTE does not borrow its underlying relation as a direct model boundary. One warning is emitted per authored SQL expression; no automatic rewrite moves transaction or locking boundaries.",
        ),
        examples=(
            RuleExample(
                example_id="cross-model-join",
                title="Separate model relations share one SQL projection",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/scenario_store.py", _BAD),),
                focus_path=PurePosixPath("app/scenario_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="self-join",
                title="A self join does not prove distinct model ownership",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/scenario_store.py", _BAD.replace('"user" u', "scenario u")),),
                focus_path=PurePosixPath("app/scenario_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None or is_test_path(context.path):
            return []
        findings: dict[tuple[int, int], Diagnostic] = {}
        for query in store_queries(context):
            if not _cross_relation_join(query.statement):
                continue
            node = query.node
            findings[node.lineno, node.col_offset] = Diagnostic(
                context.path,
                node.lineno,
                node.col_offset + 1,
                self.code,
                "Review this join across distinct PostgreSQL relations; prefer bounded typed store reads and application composition. Preserve tenant filters, cardinality, snapshot consistency and root-row locks; retain an explained exception when atomic SQL is required.",
                severity=Severity.WARNING,
            )
        return sorted(findings.values(), key=lambda finding: (finding.line, finding.col))


def _cross_relation_join(statement: exp.Expr) -> bool:
    from sqlglot.optimizer.scope import traverse_scope  # ruff: ignore[import-outside-top-level] -- resolve CTE references per native query scope.

    for scope in traverse_scope(statement):
        relations = _direct_relations(scope)
        if any(
            _distinct_relations(left, right) for index, left in enumerate(relations) for right in relations[index + 1 :]
        ):
            return True
    return False


def _direct_relations(scope: Scope) -> list[tuple[str, ...]]:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- native query scope relation identities.

    select = scope.expression
    if not isinstance(select, exp.Select) or not select.args.get("joins"):
        return []
    from_clause = sql_child(select, "from_")
    root = sql_child(from_clause, "this") if isinstance(from_clause, exp.From) else None
    nodes = [root, *(sql_child(join, "this") for join in sql_children(select, "joins") if isinstance(join, exp.Join))]
    aliases = [node.alias_or_name for node in nodes if isinstance(node, exp.Table)]
    if len(aliases) != len(set(aliases)):
        return []
    resolved: list[tuple[str, ...]] = []
    for node in nodes:
        if not isinstance(node, exp.Table) or not isinstance(scope.sources.get(node.alias_or_name), exp.Table):
            continue
        key = relation_key(node)
        if key is not None:
            resolved.append(key)
    return resolved


def _distinct_relations(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    # Mixed qualification cannot prove whether search_path resolves one spelling to the other.
    return len(left) == len(right) and left != right
