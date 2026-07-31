# SARJ020 `no-aggregation-in-store-query` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_aggregation_in_store_query.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

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
