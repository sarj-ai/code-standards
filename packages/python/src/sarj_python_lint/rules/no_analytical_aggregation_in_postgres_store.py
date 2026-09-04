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


def _analytical_signal(sql: str) -> str | None:
    for label, pattern in _STRONG_ANALYTICAL:
        if pattern.search(sql):
            return label
    if _TIME_BUCKET.search(sql) and _GROUP_BY.search(sql) and _COMMON_AGGREGATE.search(sql):
        return "time-bucketed GROUP BY"
    return None


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
            "Only statistical aggregates and time-bucketed grouped rollups are reported; ordinary operational aggregates are intentionally excluded.",
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
            signal = _analytical_signal(sql)
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
