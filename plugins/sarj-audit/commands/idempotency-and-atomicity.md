# Idempotency and atomicity

Audit runtime race conditions and retry safety using the shared [audit protocol](../README.md#audit-protocol). Migration DDL belongs in `database-schemas-and-migrations`.

## Automated baseline

Run applicable `insert-requires-on-conflict`, `store-insert-requires-on-conflict`, `require-lock-timeout`, and database concurrency checks.

## Judgment checks

- Check-then-insert/update sequences that are not protected by a unique constraint, atomic statement, transaction, or lock.
- Multi-write operations that can expose partial state on failure.
- Retried requests, jobs, webhooks, or message handlers without stable idempotency keys and durable deduplication.
- Read-modify-write updates vulnerable to lost updates or stale reads.
- External side effects performed before durable state makes retries safe.

Judge atomicity at the real consistency boundary. A process-local mutex is not sufficient across replicas, and a database transaction cannot roll back a remote API call.
