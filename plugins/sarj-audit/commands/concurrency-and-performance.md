# Concurrency and performance

Audit concurrency correctness and material performance problems using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).

## Judgment checks

- Blocking filesystem, network, subprocess, or database calls on an event loop.
- Independent operations awaited serially, unbounded fan-out, detached work without lifecycle/error ownership, or cancellation leaks.
- N+1 queries, repeated remote calls, unnecessary full materialization, and expensive work repeated in hot paths.
- UI main-thread work, unstable component definitions, and memoization that adds cost without evidence.

Distinguish correctness defects from optimization ideas. Require profiling, query evidence, or a clear complexity argument for performance-only findings.

## Database batches and query cost

Use an existing `get_many`/`upsert_many` store operation for independent work
whose access, failure and result contracts match. Fetch shared reference data
once and join it by key in memory when that avoids demonstrated N+1 reads. Do
not replace a serial database loop with unbounded `gather` or `Promise.all`;
that can exhaust the pool while preserving every query.

Keep batch size and in-flight work bounded by measured latency, parameter count,
payload size, memory, lock duration and pool capacity. Retain streaming and
backpressure for unbounded inputs. Do not choose a universal batch-size constant.
Use parameterized set-based SQL, the driver's batch API, or a staging/COPY path
suited to the workload; `executemany` is repeated statement execution and does
not make it one set-based SQL statement. With Psycopg, prefer its existing
[pipeline-aware batch support](https://www.psycopg.org/psycopg3/docs/advanced/pipeline.html)
over handwritten pipeline scaffolding.

Define duplicate conflict-key behavior before a bulk upsert. PostgreSQL
[`ON CONFLICT DO UPDATE`](https://www.postgresql.org/docs/current/sql-insert.html)
cannot affect the same existing row twice in one statement. Reject duplicates
or apply an explicit deterministic merge policy;
do not silently deduplicate if the sequential contract accumulates effects.
Keep returned rows associated with their keys; SQL result order is not the
input order unless the query establishes it. Specify empty-input behavior,
which rows are returned, partial failure and whether a whole batch is atomic.

Preserve cursor observations when replacing an execute loop. Psycopg
[`executemany`](https://www.psycopg.org/psycopg3/docs/api/cursors.html#psycopg.Cursor.executemany)
without `returning=True` accumulates affected-row counts; the last singleton
execute reports only its own count. With `returning=True`, consume each result
set using the installed version's `nextset()` or `results()` API; one
`fetchall()` reads only the current set. Keep result-dependent parameter
generation and per-row failure handling explicit.

Return database-generated values through `RETURNING` when it replaces a redundant
read without changing the result contract. Review no-op conflict updates when
they cause measured write amplification, but preserve timestamps, audit/trigger
effects and returned-row behavior: a conflict update filtered by `WHERE` can
return no row even when the row exists.
`DO NOTHING RETURNING` also omits conflicting rows. Do not zip these results
with every input or treat a missing returned row as proof that no row exists.

Keep pool ownership at the application composition boundary, bound acquisition
waits and query time to the caller's deadline, and release borrowed connections
promptly. Reusing a pool does not make unbounded concurrency safe. For operations
that lock several rows, review a consistent lock order and deadlock behavior;
preserve domain-required ordering when batching.

Distinguish pool wait, execution and commit latency when investigating slow
writes. Use measured queueing, batch sizes and affected rows to choose a change;
do not add connections solely because queries are slow. Close or fully consume
streaming results before returning their connection, including on early exit.

Inspect representative query plans and production cardinality when proposing
indexes or query rewrites. Bound result sets, project required columns, and use
stable keyset ordering with a unique tie-breaker for growing paginated data.
Keep cursor predicates, null ordering and sort direction aligned. A clean lint
result does not establish an efficient execution plan.
