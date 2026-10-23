# Idempotency and atomicity

Apply [protocol](../skills/audit-protocol/SKILL.md).

Trace races, retry identity and partial effects. Atomic writes need one
connection/transaction; process locks do not span replicas, and transactions
cannot undo remote effects. Preserve guarded updates and domain/tenant identity
in durable deduplication/outboxes.

Chunking need not commit per chunk. Psycopg nested transactions may be savepoints
inside an implicit read transaction; establish the commit owner. Retry classified
transient failures around the whole transaction with bounded backoff/cancellation.
Lost commit connections leave unknown outcomes: reconcile durable keys/receipts
before replaying non-idempotent writes.

Verify retries, rollback and affected races against the real store.
