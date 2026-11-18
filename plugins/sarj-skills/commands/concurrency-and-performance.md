# Concurrency and performance

Apply [protocol](../skills/audit-protocol/SKILL.md).

Measure performance or prove complexity gains; separate pool wait, execution and
commit cost. Check blocking, cancellation, N+1 calls, buffered uploads and
unbounded work. Bound batches/fan-out by payload, memory, locks and pool capacity;
preserve ordering/backpressure. Parallel singleton calls retain N+1 cost.

Consider combining independent awaited reads or gather batches after tracing
data dependencies and side effects. Measure request latency and the resulting
peak collaborator concurrency under the same workload. Check first-error choice,
sibling completion/cancellation and resource release; per-query timeouts do not
establish an endpoint deadline or server-side cancellation. Keep necessary
sequencing and capacity limits even when result values are independent.

Batching must preserve duplicate policy, empty input, identity and partial failure.
PostgreSQL conflict updates cannot affect one row twice; filtered updates and
`DO NOTHING RETURNING` omit rows. Never zip partial/unordered results to inputs.
Psycopg `executemany` has different counts/result sets.

Use representative plans/cardinality for indexes. Consume/close streams before
returning pooled connections. Review retry/drop/saturation/latency signals and
[transaction guarantees](idempotency-and-atomicity.md).
