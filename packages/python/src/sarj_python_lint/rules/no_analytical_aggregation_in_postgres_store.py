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
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._sql import is_store_module, sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path


# A real SQL query shape — not just the word "from", so prose/LLM-prompt strings
# (e.g. "distinct from unexpected exceptions") are not mistaken for queries.
_QUERY_SHAPE = re.compile(
    r"\bSELECT\b[\s\S]*?\bFROM\b|\bUPDATE\b[\s\S]*?\bSET\b|\bDELETE\b\s+FROM\b",
    re.IGNORECASE,
)

# ClickHouse IS the place for aggregation.
_CLICKHOUSE_FILE = re.compile(
    r"\bclickhouse_connect\b|\bclickhouse_driver\b|^\s*import\s+clickhouse\b",
    re.MULTILINE,
)
# Belt-and-braces: a single query using ClickHouse-only functions is ClickHouse.
_CLICKHOUSE_SQL = re.compile(
    r"\barg(?:Max|Min)\b|\b_peerdb|\bJSONExtract|\buniqExact\b|\bgroupArray\b"
    r"|\barrayJoin\b|\bquantile\w*\(",
)

# BigQuery IS also a place for aggregation.
_BIGQUERY_FILE = re.compile(
    r"\bfrom\s+google\.cloud\s+import\s+bigquery\b"
    r"|\bfrom\s+google\.cloud\.bigquery\b"
    r"|\bimport\s+google\.cloud\.bigquery\b",
    re.MULTILINE,
)
# Belt-and-braces: a single query with a BigQuery-only signal is BigQuery.
_BIGQUERY_SQL = re.compile(
    r"\b(?:FROM|JOIN)\s+`"
    r"|\bAPPROX_COUNT_DISTINCT\s*\(|\bGENERATE_ARRAY\s*\(|\b_PARTITIONTIME\b"
    r"|\bSAFE_CAST\s*\(|\bPARSE_TIMESTAMP\s*\(|\bCOUNTIF\s*\(|\bSTRUCT\s*\(",
    re.IGNORECASE,
)
# Psycopg placeholders are a Postgres signal that overrides otherwise ambiguous analytics syntax.
_POSTGRES_SQL = re.compile(r"%\(\w+\)s|%s")

# This null-safe comparison is a row predicate, not set deduplication.
_NULL_SAFE_COMPARISON = re.compile(r"\bIS\s+(?:NOT\s+)?DISTINCT\s+FROM\b", re.IGNORECASE)
_DISTINCT_ON = re.compile(r"\bDISTINCT\s+ON\s*\(", re.IGNORECASE)

_ANALYTIC_COUNT_SIGNAL = re.compile(
    r"\b(?:GROUP\s+BY|HAVING|FILTER)\b|\bOVER\s*\(|\bCOUNT\s*\(\s*DISTINCT\b",
    re.IGNORECASE,
)

_AGGREGATIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("COUNT(", re.compile(r"\bCOUNT[ \t]*\(", re.IGNORECASE)),
    ("SUM(", re.compile(r"\bSUM[ \t]*\(", re.IGNORECASE)),
    ("AVG(", re.compile(r"\bAVG[ \t]*\(", re.IGNORECASE)),
    ("MIN(", re.compile(r"\bMIN[ \t]*\(", re.IGNORECASE)),
    ("MAX(", re.compile(r"\bMAX[ \t]*\(", re.IGNORECASE)),
    ("ARRAY_AGG(", re.compile(r"\bARRAY_AGG[ \t]*\(", re.IGNORECASE)),
    ("STRING_AGG(", re.compile(r"\bSTRING_AGG[ \t]*\(", re.IGNORECASE)),
    ("JSON_AGG(", re.compile(r"\bJSON_AGG[ \t]*\(", re.IGNORECASE)),
    ("JSONB_AGG(", re.compile(r"\bJSONB_AGG[ \t]*\(", re.IGNORECASE)),
    ("BOOL_AND(", re.compile(r"\bBOOL_AND[ \t]*\(", re.IGNORECASE)),
    ("BOOL_OR(", re.compile(r"\bBOOL_OR[ \t]*\(", re.IGNORECASE)),
    ("EVERY(", re.compile(r"\bEVERY[ \t]*\(", re.IGNORECASE)),
    ("STDDEV(", re.compile(r"\bSTDDEV(?:_POP|_SAMP)?[ \t]*\(", re.IGNORECASE)),
    ("VARIANCE(", re.compile(r"\b(?:VARIANCE|VAR_POP|VAR_SAMP)[ \t]*\(", re.IGNORECASE)),
    ("CORR(", re.compile(r"\bCORR[ \t]*\(", re.IGNORECASE)),
    ("COVAR(", re.compile(r"\bCOVAR_(?:POP|SAMP)[ \t]*\(", re.IGNORECASE)),
    ("REGR_*(", re.compile(r"\bREGR_[A-Z_]+[ \t]*\(", re.IGNORECASE)),
    ("PERCENTILE_*(", re.compile(r"\bPERCENTILE_(?:CONT|DISC)[ \t]*\(", re.IGNORECASE)),
    ("RANGE_AGG(", re.compile(r"\bRANGE_AGG[ \t]*\(", re.IGNORECASE)),
    ("XMLAGG(", re.compile(r"\bXMLAGG[ \t]*\(", re.IGNORECASE)),
    ("GROUP BY", re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)),
    ("DISTINCT", re.compile(r"\bDISTINCT\b", re.IGNORECASE)),
)


def _blank_null_safe_comparisons(sql: str) -> str:
    sql = _NULL_SAFE_COMPARISON.sub(lambda match: " " * len(match.group(0)), sql)
    return _DISTINCT_ON.sub(lambda match: " " * len(match.group(0)), sql)


# Require both a query verb and aggregation syntax to avoid flagging unrelated prose.
_VERB_GATE = re.compile(r"select|update|delete", re.IGNORECASE)
_AGG_GATE = re.compile(
    r"count|sum|avg|min|max|array_agg|string_agg|jsonb?_agg|bool_|every|stddev|variance|var_"
    r"|corr|covar_|regr_|percentile_|range_agg|xmlagg|group|distinct|filter",
    re.IGNORECASE,
)


@final
class NoAnalyticalAggregationInPostgresStore(Rule):
    id: str = "no-analytical-aggregation-in-postgres-store"
    code: str = "SARJ020"
    documentation = RuleDocumentation(
        summary="Postgres store queries should not perform analytical aggregation.",
        rationale="Analytical aggregation competes with transactional reads and is better served by the columnar mirror.",
        remediation="Run aggregation in ClickHouse or BigQuery and keep Postgres store queries focused on point or bounded reads.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        aliases=("no-aggregation-in-store-query",),
        limitations=(
            "Only SQL string literals in recognized store modules are analyzed.",
            "Files and queries identified as ClickHouse or BigQuery are excluded.",
            "Scalar COUNT and PostgreSQL DISTINCT ON row selection are excluded unless another analytical signal is present.",
        ),
        examples=(
            RuleExample(
                example_id="postgres-aggregate-query",
                title="Postgres store query performs aggregation",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/call_store.py", 'QUERY = "SELECT SUM(amount) FROM call"\n'),),
                focus_path=PurePosixPath("app/call_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="bounded-postgres-query",
                title="Postgres store query reads bounded rows",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/call_store.py",
                        'QUERY = "SELECT id FROM call ORDER BY created_at LIMIT 50"\n',
                    ),
                ),
                focus_path=PurePosixPath("app/call_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_store_module(path):
            return []
        # Skip files whose literals cannot contain both required syntax classes.
        if _AGG_GATE.search(source) is None or _VERB_GATE.search(source) is None:
            return []
        if _CLICKHOUSE_FILE.search(source):
            return []
        bigquery_file = _BIGQUERY_FILE.search(source) is not None
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags: list[Diagnostic] = []
        consumed: set[int] = set()
        for node in nodes(tree, ast.Constant, ast.BinOp):
            if id(node) in consumed:
                continue
            text = sql_string_value(node)
            if text is None:
                continue
            # Mark concatenated children consumed so the walk cannot report the same query twice.
            if isinstance(node, ast.BinOp):
                consumed.update(id(sub) for sub in walk(node))

            if _AGG_GATE.search(text) is None or _VERB_GATE.search(text) is None:
                continue

            sql = _blank_null_safe_comparisons(strip_sql_noise(text))
            if _QUERY_SHAPE.search(sql) is None or _CLICKHOUSE_SQL.search(sql) or _BIGQUERY_SQL.search(sql):
                continue
            if bigquery_file and _POSTGRES_SQL.search(sql) is None:
                continue
            found = [label for label, pat in _AGGREGATIONS if pat.search(sql)]
            if not found:
                continue
            # A scalar COUNT is commonly a strongly consistent pagination total
            # or transactional invariant. Only COUNT with an independently
            # provable analytical shape belongs to this rule.
            if found == ["COUNT("] and _ANALYTIC_COUNT_SIGNAL.search(sql) is None:
                continue

            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"Store query uses {', '.join(found)} — push heavy "
                        "aggregation to ClickHouse / BigQuery, keep Postgres to "
                        "point/bounded reads. Suppress with `# sarj-noqa: SARJ020`."
                    ),
                )
            )
        diags.sort(key=lambda d: (d.line, d.col))
        return diags
