# Database schemas and migrations

Audit schema and migration safety using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).

## Judgment checks

- Destructive or table-rewriting changes without a staged rollout, safe backfill, compatibility window, and rollback plan.
- Catalog-query `DO` blocks or duplicate-object exception handlers added solely to make versioned transactional DDL replayable. Let the migration runner track applied versions and roll back failed transactions; review nontransactional migrations and genuinely replayed scripts separately.
- Incorrect or incomplete reversals where the migration system supports down migrations.
- Missing, redundant, or badly ordered indexes based on actual access paths and selectivity.
- Soft-delete uniqueness errors, unsafe type conversions, and constraints introduced before existing data is valid.

Database semantics are dialect-specific. Do not apply PostgreSQL-only advice such as `CONCURRENTLY` or reversible dbmate migrations to SQLite/D1. Runtime transaction races belong in `idempotency-and-atomicity`.

For service queries, justify indexes from actual equality filters, tenant scope,
join keys, ordering and selectivity. Check write amplification, overlapping
prefixes and index size before adding another index. Assess foreign-key lookup
cost on the referencing side; PostgreSQL does not automatically index that side.
Keep uniqueness and foreign keys in the database when they own durable integrity,
and preserve partial/soft-delete semantics during upsert changes.

Bind values separately from SQL text. Compose dynamic identifiers only through
the driver's identifier API or an established allowlist; values and identifiers
have different quoting rules. Keep named, validated row conversion at the store
boundary and return only the fields the consumer needs. Preserve SQL NULL's
three-valued logic when replacing predicates or optional update behavior.
