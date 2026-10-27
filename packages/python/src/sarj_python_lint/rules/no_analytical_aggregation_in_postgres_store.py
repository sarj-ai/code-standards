from __future__ import annotations

from pathlib import PurePosixPath
import re
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
from sarj_python_lint.rules._transactional_sql import query_signal, transactional_queries


if TYPE_CHECKING:
    from sqlglot import exp

    from sarj_python_lint._file_context import PythonFileContext


# Keep the historical standalone SARJ437 overlap stable. Combined runs give the
# broader SARJ020 error precedence only when it actually emits a diagnostic.
_TIME_BUCKET = re.compile(r"\b(?:DATE_TRUNC|TIME_BUCKET)\s*\(", re.IGNORECASE)
_GROUP_BY = re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)
_COMMON_AGGREGATE = re.compile(
    r"\b(?:COUNT|SUM|AVG|MIN|MAX|ARRAY_AGG|STRING_AGG|JSONB?_AGG|BOOL_AND|BOOL_OR|EVERY)\s*\(",
    re.IGNORECASE,
)
_LOCKING_READ = re.compile(r"\b(?:FOR\s+(?:NO\s+KEY\s+)?UPDATE|FOR\s+SHARE|SKIP\s+LOCKED)\b", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"%(?:\([^)]+\))?s")
_GROUP_KEYS_LIMIT = 2
_GROUP_AGGREGATES_LIMIT = 2
_SINGLE_GROUP_AGGREGATES_LIMIT = 3
_STRONG_ANALYTICAL: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("STDDEV", re.compile(r"\bSTDDEV(?:_POP|_SAMP)?\s*\(", re.IGNORECASE)),
    ("VARIANCE", re.compile(r"\b(?:VARIANCE|VAR_POP|VAR_SAMP)\s*\(", re.IGNORECASE)),
    ("CORR", re.compile(r"\bCORR\s*\(", re.IGNORECASE)),
    ("COVAR", re.compile(r"\bCOVAR_(?:POP|SAMP)\s*\(", re.IGNORECASE)),
    ("REGR", re.compile(r"\bREGR_[A-Z_]+\s*\(", re.IGNORECASE)),
    ("PERCENTILE", re.compile(r"\bPERCENTILE_(?:CONT|DISC)\s*\(", re.IGNORECASE)),
)


def analytical_signal(sql: str) -> str | None:
    if _LOCKING_READ.search(sql) is not None:
        return None
    for label, pattern in _STRONG_ANALYTICAL:
        if pattern.search(sql):
            return label
    if _TIME_BUCKET.search(sql) and _GROUP_BY.search(sql) and _COMMON_AGGREGATE.search(sql):
        return "time-bucketed GROUP BY"
    return _grouped_reporting_signal(sql)


def _grouped_reporting_signal(sql: str) -> str | None:
    import sqlglot  # ruff: ignore[import-outside-top-level] -- parse only aggregate-shaped SQL after cheap gates
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- paired with lazy parser import
    from sqlglot.errors import SqlglotError  # ruff: ignore[import-outside-top-level] -- paired with lazy parser import

    if _GROUP_BY.search(sql) is None or _COMMON_AGGREGATE.search(sql) is None:
        return None
    try:
        statements = sqlglot.parse(_PLACEHOLDER.sub("?", sql), read="postgres")
    except SqlglotError:
        return None
    for statement in statements:
        if not isinstance(statement, exp.Query):
            continue
        for select in statement.find_all(exp.Select):
            if _is_reporting_select(select):
                return "grouped reporting shape"
    return None


def _is_reporting_select(select: object) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- shared with lazy parser path

    if not isinstance(select, exp.Select):
        return False
    if _is_identity_bounded(select):
        return False
    group = select.args.get("group")
    group_count = len(group.expressions) if isinstance(group, exp.Group) else 0
    aggregate_count = sum(1 for aggregate in select.find_all(exp.AggFunc) if aggregate.parent_select is select)
    return bool(
        (group_count >= _GROUP_KEYS_LIMIT and aggregate_count >= _GROUP_AGGREGATES_LIMIT)
        or aggregate_count >= _SINGLE_GROUP_AGGREGATES_LIMIT
    )


def _is_identity_bounded(select: object) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- shared with lazy parser path

    if not isinstance(select, exp.Select):
        return False
    where = select.args.get("where")
    if not isinstance(where, exp.Where):
        return False
    equality = _expression_arg(where, "this")
    if not isinstance(equality, exp.EQ):
        return False
    left = _expression_arg(equality, "this")
    right = _expression_arg(equality, "expression")
    return (isinstance(left, exp.Column) and left.name.casefold() == "id" and not isinstance(right, exp.Column)) or (
        isinstance(right, exp.Column) and right.name.casefold() == "id" and not isinstance(left, exp.Column)
    )


def _expression_arg(node: exp.Expr, key: str) -> exp.Expr | None:
    return next((child for child in node.iter_expressions() if child.arg_key == key), None)


@final
class NoAnalyticalAggregationInPostgresStore(Rule):
    id: str = "no-analytical-aggregation-in-postgres-store"
    code: str = "SARJ020"
    documentation = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="Keep DISTINCT, GROUP BY, and SQL aggregates in analytical databases.",
        rationale=(
            "Project architecture reserves deduplication, grouping, and aggregate queries for ClickHouse "
            "or another analytical database, so reporting work does not compete with transactional reads. "
            "This is a datastore policy; SQL syntax alone cannot establish a query's execution cost."
        ),
        remediation=(
            "Move reporting and aggregation to ClickHouse or another analytical database with an explicit "
            "freshness contract. Use an indexed EXISTS or direct row lookup for operational existence checks. "
            "Preserve atomicity for transactional invariants; use an exact, explained SARJ020 exception when "
            "a reviewed invariant must remain in the transactional database."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        aliases=("no-aggregation-in-store-query", "no-analytical-queries-in-transactional-db"),
        limitations=(
            "Statically recoverable SQL in non-test, non-generated Python modules with native PostgreSQL, MySQL, or SQLite imports is analyzed, regardless of filename. The historical SARJ020 identifier is retained.",
            "Every parsed SELECT DISTINCT (including DISTINCT ON), deduplicating UNION/INTERSECT/EXCEPT, GROUP BY, and built-in SQL aggregate is reported, including CTEs, nested writes, windowed aggregates, identity-bounded queries, and LIMIT queries. ALL set operations remain valid. This deliberately replaces the former reporting-size thresholds.",
            "A single imported backend owns module SQL. Resolvable first-party query contracts and re-exports retain their native analytical-provider evidence. Mixed backend modules require a direct query sink on a source-proven native connection or annotated parameter; unresolved receivers and separately bound queries abstain.",
            "Known ClickHouse, BigQuery, DuckDB, Snowflake, Trino, Athena, and Databricks drivers are analytical owners. Comments, scalar SQL values, identifiers, Python docstrings, and IS DISTINCT FROM do not trigger the policy.",
            "SQLite multi-argument MIN/MAX and MySQL ANY_VALUE retain their scalar semantics; PostgreSQL ANY_VALUE remains an aggregate.",
            "PostgreSQL pg_catalog aggregates and lowercase quoted built-ins retain native identity. Unknown schemas and distinct quoted uppercase PostgreSQL function names abstain. Executing EXPLAIN ANALYZE is analyzed; plan-only EXPLAIN and unsupported PostgreSQL EXPLAIN options abstain.",
            "Dynamic SQL grammar, ORM expression trees, unknown wrappers, user-defined aggregates, and malformed SQL are not inferred. No automatic datastore migration is safe.",
        ),
        examples=(
            RuleExample(
                example_id="postgres-reporting-rollup",
                title="PostgreSQL computes a time-series reporting rollup",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/event_store.py",
                        "import psycopg\n\n"
                        "QUERY = \"SELECT DATE_TRUNC('day', occurred_at), COUNT(*), AVG(latency_ms) "
                        'FROM event GROUP BY 1"\n',
                    ),
                ),
                focus_path=PurePosixPath("app/event_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="operational-existence-lookup",
                title="PostgreSQL performs an operational existence lookup",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/account_store.py",
                        'import psycopg\n\nQUERY = "SELECT EXISTS(SELECT 1 FROM ledger WHERE account_id = %s)"\n',
                    ),
                ),
                focus_path=PurePosixPath("app/account_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if context.tree is None or is_test_path(path) or context.generated:
            return []
        diagnostics: list[Diagnostic] = []
        for candidate in transactional_queries(context):
            signal = query_signal(candidate.sql, dialect=candidate.dialect)
            if signal is None:
                continue
            node = candidate.node
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.ERROR,
                    message=(
                        f"{signal} belongs in ClickHouse or another analytical database under project policy. "
                        "Use EXISTS or direct row lookups for operational reads. Preserve atomicity; "
                        "a transactional invariant requires an exact, explained SARJ020 exception."
                    ),
                )
            )
        diagnostics.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diagnostics
