Audit database schemas and migration files for design flaws and unsafe operations. The goal is to prevent production incidents caused by table locking, data loss, race conditions, or poor query performance. This audit focuses on patterns in SQL migration files (used with tools like Alembic, Drizzle, or `db-migrate`) and the application code that interacts with the database.

## What this audits

This audit focuses on common pitfalls in database schema design and migration execution, derived from real-world code reviews:

- **Unsafe Migrations:** DDL operations that can cause downtime. This includes `CREATE INDEX` without `CONCURRENTLY`, adding columns with `NOT NULL` and a `DEFAULT` in a single step, or data backfills with overly aggressive lock timeouts.
- **Idempotency and Reversibility:** Migrations that fail if run twice (`CREATE TABLE` without `IF NOT EXISTS`) or have incorrect `down` migrations, making rollbacks impossible.
- **Concurrency Issues:** Application logic with "check-then-insert" patterns that are vulnerable to race conditions, instead of using atomic database operations like `INSERT ... ON CONFLICT`.
- **Indexing Flaws:** Missing indexes that lead to slow queries and full table scans, as well as redundant or inefficient indexes that waste space and slow down writes.
- **Schema Design Flaws:** Using inflexible types like native database `ENUM`s, implementing soft-deletes in a way that breaks `UNIQUE` constraints, or denormalizing data unnecessarily.

## Phase 0: Discover project structure

Run the shared **[stack-detection](./stack-detection.md)** pass first. **Critically for this rule: detect the DB dialect and migration tool.** Postgres + dbmate (e.g. `bulbul`, `ai/python`) ⇒ the `CONCURRENTLY`, native-`ENUM`-lock, `ADD COLUMN NOT NULL DEFAULT` rewrite, and reversible `-- migrate:down` checks all apply. D1/SQLite + `wrangler d1` (e.g. `automations`) ⇒ these are **invalid or N/A**: migrations are append-only (no down concept — do **not** flag a missing down-migration), there is no `CONCURRENTLY` and no native `ENUM`, and `CREATE INDEX` is not a concurrency hazard. Name the real tools (`dbmate`, `wrangler d1`), not Alembic/Drizzle. Then add the skill-specific items:

1.  **Detect migration tool and directory** — Check for `alembic.ini`, `drizzle.config.ts`, `database.json` (`db-migrate`), `*.sql` files in a `migrations` or `db/migrations` directory, or other common migration tool configurations to find migration files.
2.  **Find all migration files** — List all `.sql` or language-specific (`.py`, `.ts`) files within the detected migration directory.
3.  **Detect database dialect** — Determine if the target database is PostgreSQL, MySQL, or SQLite, as safety rules are dialect-specific.
4.  **Partition into agents** — Create one agent for each of the concerns in Phase 1.

Output the discovered structure before proceeding.

## Phase 1: Audit (parallel agents)

Spawn agents to search all migration files and relevant application code for the following violations. Each agent should report the file, line number, the problematic code, and a description of the risk.

### Agent assignments

1.  **Unsafe & Non-Idempotent Migrations Agent:**
    -   Scan `up` migrations for DDL statements (`CREATE TABLE`, `CREATE TYPE`, `ADD COLUMN`, `CREATE EXTENSION`) that are missing `IF NOT EXISTS` clauses. (Medium Severity)
    -   Scan for `CREATE INDEX` statements on existing tables that are missing the `CONCURRENTLY` keyword (PostgreSQL). This takes a strong lock that blocks writes. (High Severity)
    -   Scan for modifications to migration files that have likely already been run in production environments (based on filename/timestamp conventions). (High Severity)
    -   For each migration, check if the `down` migration is missing, is a no-op (e.g., `SELECT 1;`), or does not correctly reverse the `up` migration (e.g., `up` creates a table, `down` does not drop it). (Medium Severity)
    -   Scan for `ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT ...` on existing tables, which can cause full table locks on older PostgreSQL versions (pre-11) or with volatile defaults. (High Severity)

2.  **Schema Design & Constraints Agent:**
    -   Scan for `CREATE TYPE ... AS ENUM`. These are hard to modify without downtime. Suggest a `TEXT` column with a `CHECK` constraint or a lookup table instead. (Low Severity)
    -   Scan for `UNIQUE` constraints on tables that also have a soft-delete column (e.g., `deleted_at`). This pattern breaks re-creation of deleted entities. (High Severity)
    -   Scan for columns that look like foreign keys by name (e.g., `user_id`, `organization_id`) but are missing a `REFERENCES` constraint. (Medium Severity)
    -   Scan for boolean flags (e.g., `is_active`) and suggest using a more flexible `status TEXT` column instead, which can accommodate more states in the future without schema changes. (Low Severity)

3.  **Indexing & Query Performance Agent:**
    -   Scan for `INSERT ... ON CONFLICT (column)` where `column` does not have a `UNIQUE` index or constraint, which will cause a runtime error. (High Severity)
    -   Scan for "check-then-insert" patterns in application code (e.g., `await db.get(...)` followed by `await db.insert(...)`) which are prone to race conditions. (High Severity)
    -   Scan for missing indexes on foreign key columns or columns frequently used in `WHERE` clauses. (Medium Severity)
    -   Scan for redundant indexes. For example, an index on `(col_a)` is redundant if an index already exists on `(col_a, col_b)`. (Low Severity)

## Phase 2: Compile findings

After all agents report back, compile a single summary table with columns:

| File | Line | Unsafe Pattern | Risk | Severity |
|------|------|----------------|------|----------|

Sort by severity (high first), then by file path.

Group the summary into:
-   **High Severity** — Operations that will cause downtime, data corruption, or runtime errors (blocking DDL, race conditions, broken constraints).
-   **Medium Severity** — Issues that complicate deployments, cause performance degradation, or risk data integrity (non-idempotent/reversible migrations, missing indexes).
-   **Low Severity** — Inflexible schema designs or code style issues that increase future maintenance costs (`ENUM`s, redundant indexes).

## Phase 3: Generate fix plan

For each high or medium severity finding, output a concrete remediation plan:
-   **For Blocking `CREATE INDEX`:** "Add the `CONCURRENTLY` keyword to create the index without locking the table against writes. Note that this must be run outside a transaction block in PostgreSQL." [2, 8, 9, 10, 11]
-   **For Soft-Delete/Unique Conflict:** "Replace the `UNIQUE` constraint with a partial unique index: `CREATE UNIQUE INDEX ... ON table(columns) WHERE deleted_at IS NULL;`. This enforces uniqueness only for active rows." [13, 17, 29, 31, 38]
-   **For Race Conditions:** "Replace the `SELECT` then `INSERT` logic with a single atomic `INSERT ... ON CONFLICT (columns) DO UPDATE SET ...` or `DO NOTHING` statement."
-   **For Non-Idempotent DDL:** "Add `IF NOT EXISTS` to the `CREATE TABLE`/`ADD COLUMN` statement to make the migration safely re-runnable." [23, 24, 25, 28, 33]
-   **For Native ENUMs:** "Replace `CREATE TYPE ... AS ENUM` with a `TEXT` column and a `CHECK` constraint, or a foreign key to a lookup table. This is easier to modify without downtime." [18, 27, 34, 37, 39]
-   **For Missing Index on Foreign Key:** "Add an index on the foreign key column(s) to avoid performance degradation on `UPDATE` and `DELETE` operations on the parent table and to speed up `JOIN` queries." [14, 32, 35, 36]
-   **For Modifying Executed Migrations:** "Create a new migration file to apply the required changes instead of editing a migration that has already been applied to other environments. This prevents schema inconsistencies." [4, 40, 46]

Do NOT automatically implement fixes. Present the plan for review and wait for confirmation before making changes.
