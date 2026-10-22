# Database schemas and migrations

Use the [audit protocol](../skills/audit-protocol/SKILL.md).

Review destructive changes, backfills, compatibility/rollback windows and
constraints against existing data. Native migration rules own static DDL checks;
judge reversals and nontransactional recovery against the actual runner/dialect.

Justify indexes from plans, cardinality, tenant filters and write cost; preserve
partial/nullable/soft-delete integrity. Bind values and compose identifiers through
the driver's API. Preserve SQL NULL semantics.

For pooled tenant/role settings, verify the protected query uses the same
connection and intended lifetime: PostgreSQL `SET LOCAL` is transaction-local,
while session `SET` can reach the next borrower. Respect other verified isolation
mechanisms and pool reset contracts.
