# Idempotency and atomicity

Audit runtime race conditions and retry safety using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol). Migration DDL belongs in `database-schemas-and-migrations`.

## Judgment checks

- Check-then-insert/update sequences that are not protected by a unique constraint, atomic statement, transaction, or lock.
- Multi-write operations that can expose partial state on failure.
- Retried requests, jobs, webhooks, or message handlers without stable idempotency keys and durable deduplication.
- Read-modify-write updates vulnerable to lost updates or stale reads.
- External side effects performed before durable state makes retries safe.

Judge atomicity at the real consistency boundary. A process-local mutex is not sufficient across replicas, and a database transaction cannot roll back a remote API call.

For a logical multi-write operation, share one connection and explicit transaction
through the owning unit of work. Separate store methods borrowing separate pool
connections are not made atomic by an outer transaction on another connection.
Keep network calls and long computation outside lock-holding transactions when
the business invariant permits it. Coordinate durable state and outbound effects
with the established outbox or idempotent delivery mechanism.

An upsert's conflict target must match the real identity and tenant boundary,
including nullable keys, soft deletion and partial uniqueness where applicable.
Do not replace a database constraint with check-then-insert application code.
Use atomic expressions for increments and conditional writes/version checks for
stale updates; a broad upsert must not erase these concurrency guarantees.

Retry only classified transient failures, at the complete transaction boundary,
with bounded attempts and backoff. Reusing an aborted transaction or retrying
only the last statement can leave the operation invalid or incomplete. Preserve
cancellation and the distinction between conflict, missing row and success.
Do not retry syntax, validation, authorization or integrity failures blindly.
Use the driver's structured SQLSTATE/diagnostics for classification rather than
rendered error text. PostgreSQL's
[serialization-failure guidance](https://www.postgresql.org/docs/current/mvcc-serialization-failure-handling.html)
explains why retrying the complete transaction includes the logic that selected
its statements and values.

Exercise insertion, conflict updates, omitted/cleared fields, repeated requests,
empty batches, duplicate keys, missing rows, tenant isolation and failure rollback
at the store boundary. Add concurrency coverage when the operation depends on
locking or compare-and-swap; test the observable invariant rather than SQL text
or an exact number of internal helper calls.
