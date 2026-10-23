# Database schemas and migrations

Apply [protocol](../skills/audit-protocol/SKILL.md).

Check backfills, existing-data constraints, compatibility/rollback windows and
nontransactional recovery against the runner/dialect. Justify indexes with plans,
cardinality, tenant filters and write cost; preserve nullable/partial/soft-delete
integrity and SQL NULL semantics. Bind values; compose identifiers through the
driver.

Tenant/role settings must govern the protected query on the same connection:
PostgreSQL `SET LOCAL` lasts a transaction; session `SET` can leak to the next
borrower. Account for verified isolation and pool-reset contracts.
