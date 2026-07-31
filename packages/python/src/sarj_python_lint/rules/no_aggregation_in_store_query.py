"""SARJ020: no DISTINCT / GROUP BY / COUNT in a store query — aggregate elsewhere.

Heavy aggregation (`COUNT`, `GROUP BY`, `DISTINCT`) does not belong in the
transactional Postgres store layer: it scans, sorts, and hashes large row sets
on the primary, competing with the latency-critical OLTP path. The house
direction is to push aggregate/analytical reads to the columnar mirror
(ClickHouse / BigQuery), where they are cheap, and keep Postgres queries to
point lookups and small bounded reads.

This rule walks SQL string literals embedded in `.py` (`*_store.py`) and flags
any query (a string containing `FROM`) that uses `COUNT(`, `GROUP BY`, or
`DISTINCT`. SQL string-literal values and `--` / `/* */` comments are neutralized
first, so an aggregate keyword or a backtick living inside a quoted value never
affects the result.

    # flagged
    "SELECT status, COUNT(*) FROM call GROUP BY status"
    "SELECT DISTINCT org_id FROM call"

    # preferred
    point/bounded reads in Postgres; aggregate in ClickHouse/BigQuery.

Queries against the columnar mirrors are exempt: a file importing the ClickHouse
SDK, or a single query using ClickHouse-only functions or BigQuery syntax
(backtick-quoted table identifiers, BQ-only functions), is not a Postgres store
query and is out of scope. A file-level BigQuery-SDK import exempts only queries
that carry no Postgres-specific signal — a psycopg `%s` placeholder marks a real
Postgres store query even in a mixed analytics module.

EXEMPTIONS ADDED FROM A FIRST-PARTY REVIEW REGRESSION (11 suppressed hits at the
reviewed head; none was a defect):

* `IS [NOT] DISTINCT FROM` is Postgres' NULL-SAFE COMPARISON OPERATOR, not the
  set-deduplicating `DISTINCT`. It is a per-row predicate that does exactly what
  `=` does except on NULLs, so it costs nothing this rule cares about; it merely
  shares a keyword with `SELECT DISTINCT`. The operator is blanked before the
  aggregation scan, so the rest of the query is still judged normally.
  Evidence: one first-party store site — an
  `INSERT ... ON CONFLICT DO UPDATE ... WHERE orders.organization_id
  IS NOT DISTINCT FROM EXCLUDED.organization_id` upsert containing no aggregation
  at all.
* TEST FILES are not store modules (`_sql.is_store_module`). `test_<x>_store.py`
  ends in `_store.py`, so the store-layer naming test used to sweep in the tests
  *for* the store layer. A `COUNT(*)` in a test asserts over a handful of
  per-test fixture rows and never runs on the OLTP primary, so the rule's whole
  premise is absent. Evidence: three first-party sites across two store test
  modules.

If an aggregate genuinely must run on Postgres (e.g. a tiny bounded admin
count), suppress with `# sarj-noqa: SARJ020 — <reason>`.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
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

# ClickHouse IS the place for aggregation. A file that talks to ClickHouse (the
# columnar mirror) is exempt — only Postgres store queries are in scope.
_CLICKHOUSE_FILE = re.compile(
    r"\bclickhouse_connect\b|\bclickhouse_driver\b|^\s*import\s+clickhouse\b",
    re.MULTILINE,
)
# Belt-and-braces: a single query using ClickHouse-only functions is ClickHouse.
_CLICKHOUSE_SQL = re.compile(
    r"\barg(?:Max|Min)\b|\b_peerdb|\bJSONExtract|\buniqExact\b|\bgroupArray\b"
    r"|\barrayJoin\b|\bquantile\w*\(",
)

# BigQuery IS also a place for aggregation. Analytics/reporting services read the
# columnar BigQuery mirror, where COUNT / GROUP BY / DISTINCT are the whole point.
# A file that imports the BigQuery SDK exempts its queries — but only those with no
# Postgres-specific signal, so a mixed module's real Postgres store query is still
# flagged (see _POSTGRES_SQL below).
_BIGQUERY_FILE = re.compile(
    r"\bfrom\s+google\.cloud\s+import\s+bigquery\b"
    r"|\bfrom\s+google\.cloud\.bigquery\b"
    r"|\bimport\s+google\.cloud\.bigquery\b",
    re.MULTILINE,
)
# Belt-and-braces: a single query with a BigQuery-only signal is BigQuery. Backtick-
# quoted table identifiers (`project.dataset.table` / `{table}`) are BQ syntax — a
# Postgres/OLTP query never uses backticks — as are BQ-only functions. ARRAY_AGG /
# UNNEST / DATE_TRUNC are deliberately EXCLUDED: they exist in Postgres too, so they
# are not BigQuery signals.
_BIGQUERY_SQL = re.compile(
    r"\b(?:FROM|JOIN)\s+`"
    r"|\bAPPROX_COUNT_DISTINCT\s*\(|\bGENERATE_ARRAY\s*\(|\b_PARTITIONTIME\b"
    r"|\bSAFE_CAST\s*\(|\bPARSE_TIMESTAMP\s*\(|\bCOUNTIF\s*\(|\bSTRUCT\s*\(",
    re.IGNORECASE,
)
# A psycopg parameter placeholder (`%s` / `%(name)s`) is Postgres-specific — BigQuery
# parameterizes with `@name`. Its presence marks a real Postgres store query, defeating
# the file-level BigQuery-import exemption. String values are masked before this scan,
# so a literal `%` inside a `LIKE` pattern can't false-signal.
_POSTGRES_SQL = re.compile(r"%\(\w+\)s|%s")

# `IS [NOT] DISTINCT FROM` is Postgres' null-safe comparison OPERATOR — it is a
# per-row predicate in a WHERE/ON/DO-UPDATE clause and does nothing an equality
# test doesn't. It shares only the spelling with `SELECT DISTINCT` / `COUNT(
# DISTINCT ...)`, the set-deduplicating constructs this rule exists to find,
# which is why the bare `\bDISTINCT\b` scan mis-read it. Blanked before the
# aggregation scan so the surrounding query is still judged on its real content.
# Evidence from a first-party review regression: an `INSERT ... ON CONFLICT DO
# UPDATE ... WHERE organization_id IS NOT DISTINCT FROM EXCLUDED.organization_id`
# upsert with no aggregation anywhere.
_NULL_SAFE_COMPARISON = re.compile(r"\bIS\s+(?:NOT\s+)?DISTINCT\s+FROM\b", re.IGNORECASE)

_AGGREGATIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("COUNT(", re.compile(r"\bCOUNT\s*\(", re.IGNORECASE)),
    ("GROUP BY", re.compile(r"\bGROUP\s+BY\b", re.IGNORECASE)),
    ("DISTINCT", re.compile(r"\bDISTINCT\b", re.IGNORECASE)),
)


def _blank_null_safe_comparisons(sql: str) -> str:
    """Blank out `IS [NOT] DISTINCT FROM` operators, preserving length and newlines.

    Returns:
        `sql` with every null-safe comparison operator replaced by spaces.

    """
    return _NULL_SAFE_COMPARISON.sub(lambda m: " " * len(m.group(0)), sql)


# A diagnostic needs BOTH a query shape (SELECT/UPDATE/DELETE) and an aggregation
# (COUNT/GROUP/DISTINCT). Noise-stripping only ever blanks characters to spaces, so
# it can never introduce a contiguous keyword the raw literal lacks — a literal
# missing either substring class can never be flagged. Gate on two cheap linear
# scans before the expensive noise-strip and backtracking query-shape regex so
# large non-SQL prompt strings (which often contain "distinct"/"count"/"group" as
# prose but no query verb) are dismissed.
_VERB_GATE = re.compile(r"select|update|delete", re.IGNORECASE)
_AGG_GATE = re.compile(r"count|group|distinct", re.IGNORECASE)


class NoAggregationInStoreQuery(Rule):
    """DISTINCT / GROUP BY / COUNT in a store query — aggregate in ClickHouse."""

    id: str = "no-aggregation-in-store-query"
    code: str = "SARJ020"
    description: str = (
        "DISTINCT / GROUP BY / COUNT in a Postgres store query — push heavy "
        "aggregation to the columnar mirror (ClickHouse / BigQuery)."
    )

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_store_module(path):
            return []
        # A diagnostic needs some string literal that carries both a query verb
        # and an aggregation keyword; `source` is a strict superset of every
        # literal, so if either class is absent from the whole file no diagnostic
        # is possible — skip the parse and full-tree walk entirely. Most files in
        # a store-lint sweep are not SQL-bearing, so this is the dominant win.
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
            # Only a `+`-concatenated BinOp owns sub-nodes that the walk would
            # otherwise re-process; mark those consumed. A plain Constant has no
            # such descendants, and if it is itself a child of a string BinOp the
            # parent (visited first in this BFS walk) already consumed it — so the
            # per-Constant subtree walk is pure overhead on large literal-heavy
            # files (the dominant cost here).
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
