# Concurrency and performance

Use the [audit protocol](../skills/audit-protocol/SKILL.md).

Review blocking event-loop work, lifecycle/cancellation leaks, N+1 calls and
unbounded materialization or fan-out. Performance-only findings need measurements
or a clear complexity argument; separate pool wait, execution and commit cost.

Prefer compatible existing bulk operations; parallel singleton queries preserve
N+1 cost. Bound batches and concurrency by actual payload, memory, locks and pool
capacity; preserve streaming/backpressure and dependent ordering.

Batch rewrites must preserve duplicate-key policy, empty input, row identity,
partial failure and atomicity. PostgreSQL conflict updates cannot affect one row
twice; filtered updates and `DO NOTHING RETURNING` can omit rows. Never zip
partial/unordered results to all inputs. Psycopg `executemany` row counts and
multiple returned result sets differ from singleton execution.

Use representative plans/cardinality before proposing indexes or rewrites.
Release or consume streaming results before returning pooled connections, even
on early exit. Review transaction/retry guarantees under
[idempotency](idempotency-and-atomicity.md).
