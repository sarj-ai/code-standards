# Concurrency and performance

Apply [protocol](../skills/audit-protocol/SKILL.md).

Measure performance or prove complexity gains; separate pool wait, execution and
commit cost. Check blocking, cancellation, N+1 calls, buffered uploads and
unbounded work. Bound batches/fan-out by payload, memory, locks and pool capacity;
preserve ordering/backpressure. Parallel singleton calls retain N+1 cost.

Batching must preserve duplicate policy, empty input, identity and partial failure.
PostgreSQL conflict updates cannot affect one row twice; filtered updates and
`DO NOTHING RETURNING` omit rows. Never zip partial/unordered results to inputs.
Psycopg `executemany` has different counts/result sets.

Use representative plans/cardinality for indexes. Consume/close streams before
returning pooled connections. Review retry/drop/saturation/latency signals and
[transaction guarantees](idempotency-and-atomicity.md).
