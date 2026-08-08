# Database schemas and migrations

Audit schema and migration safety using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).

## Judgment checks

- Destructive or table-rewriting changes without a staged rollout, safe backfill, compatibility window, and rollback plan.
- Incorrect or incomplete reversals where the migration system supports down migrations.
- Missing, redundant, or badly ordered indexes based on actual access paths and selectivity.
- Soft-delete uniqueness errors, unsafe type conversions, and constraints introduced before existing data is valid.

Database semantics are dialect-specific. Do not apply PostgreSQL-only advice such as `CONCURRENTLY` or reversible dbmate migrations to SQLite/D1. Runtime transaction races belong in `idempotency-and-atomicity`.
