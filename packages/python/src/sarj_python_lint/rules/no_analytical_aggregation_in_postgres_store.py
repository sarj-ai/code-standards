from __future__ import annotations

import ast
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
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._sql import is_store_module, sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path

    from sqlglot import exp


_QUERY_SHAPE = re.compile(r"\bSELECT\b[\s\S]*?\bFROM\b", re.IGNORECASE)
_POSTGRES_OWNER = re.compile(
    r"\b(?:psycopg|psycopg2|asyncpg|Postgres(?:ql)?|postgres_pool)\b"
    r"|sqlalchemy\.dialects\.postgresql",
    re.IGNORECASE,
)
_CLICKHOUSE_SQL = re.compile(
    r"\barg(?:Max|Min)\b|\b_peerdb|\bJSONExtract|\buniqExact\b|\bgroupArray\b"
    r"|\barrayJoin\b|\bquantile\w*\(",
)
_BIGQUERY_SQL = re.compile(
    r"\b(?:FROM|JOIN)\s+`|\bAPPROX_COUNT_DISTINCT\s*\(|\bGENERATE_ARRAY\s*\("
    r"|\b_PARTITIONTIME\b|\bSAFE_CAST\s*\(|\bPARSE_TIMESTAMP\s*\("
    r"|\bCOUNTIF\s*\(|\bSTRUCT\s*\(",
    re.IGNORECASE,
)
_MUTATION = re.compile(r"^\s*(?:UPDATE|DELETE|INSERT)\b", re.IGNORECASE)
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


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    result: set[int] = set()
    for owner in nodes(tree, ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef):
        body = owner.body
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            result.add(id(value))
    return result


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
        summary="Potentially analytical PostgreSQL store queries require review.",
        rationale=(
            "Unbounded reporting and statistical scans can compete with transactional reads. "
            "Transactional invariants, queue coordination, bounded hydration, and other strongly "
            "consistent operational aggregates remain valid PostgreSQL work."
        ),
        remediation=(
            "Review the query bounds and execution plan. Move reporting scans to the repository's "
            "columnar store, or document why the aggregate must remain transactional."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        aliases=("no-aggregation-in-store-query",),
        limitations=(
            "Only SQL string literals in recognized store modules with positive PostgreSQL ownership evidence are analyzed.",
            "Statistical aggregates, time-bucketed rollups, and broad grouped reporting shapes are reported; locked coordination reads and identity-bounded aggregates are excluded.",
            "ClickHouse- and BigQuery-specific query syntax is excluded per query, including in mixed-backend modules.",
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
                example_id="bounded-transactional-aggregate",
                title="PostgreSQL preserves a bounded transactional invariant",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/account_store.py",
                        'import psycopg\n\nQUERY = "SELECT SUM(amount) FROM ledger WHERE account_id = %s FOR UPDATE"\n',
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
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_store_module(path) or is_generated(path, source) or _POSTGRES_OWNER.search(source) is None:
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        docstrings = _docstring_node_ids(tree)
        diagnostics: list[Diagnostic] = []
        consumed: set[int] = set()
        for node in nodes(tree, ast.Constant, ast.BinOp):
            if id(node) in consumed or id(node) in docstrings:
                continue
            text_value = sql_string_value(node)
            if text_value is None:
                continue
            if isinstance(node, ast.BinOp):
                consumed.update(id(child) for child in walk(node))

            sql = strip_sql_noise(text_value)
            if (
                _QUERY_SHAPE.search(sql) is None
                or _MUTATION.search(sql)
                or _CLICKHOUSE_SQL.search(sql)
                or _BIGQUERY_SQL.search(sql)
            ):
                continue
            signal = analytical_signal(sql)
            if signal is None:
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"Possible analytical PostgreSQL query ({signal}); review its bounds and execution plan. "
                        "Move reporting scans to the columnar store, or document why this aggregate must remain transactional."
                    ),
                )
            )
        diagnostics.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diagnostics
