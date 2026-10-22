# Idempotency and atomicity

Use the [audit protocol](../skills/audit-protocol/SKILL.md).

Trace races, lost updates, retry keys and partial effects at the real consistency
boundary. Multi-write atomicity requires the same connection/transaction;
process mutexes do not span replicas and transactions cannot undo remote effects.
Use established durable deduplication/outbox mechanisms and domain-correct
conflict/tenant identity, preserving guarded updates.

Chunking need not commit each chunk. Psycopg nested transactions may be savepoints
inside an implicit read transaction; establish the actual commit owner.

Retry classified transient failures at the complete transaction boundary with
bounded backoff, preserving cancellation. Use structured diagnostics. A lost
commit connection leaves an unknown outcome: reconcile the durable key/receipt
before replaying a non-idempotent write.

Verify repeated requests, failure rollback and affected concurrency contracts at
the real store boundary; do not substitute SQL-spelling assertions.
