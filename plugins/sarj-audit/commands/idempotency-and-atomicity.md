Audit the codebase for operations that are not atomic or idempotent, which can lead to data corruption, duplicate side effects, and inconsistent state in distributed and concurrent environments.

## What this audits

This audit focuses on common concurrency and data integrity issues in code that interacts with databases or external APIs. It flags patterns that violate atomicity (all-or-nothing execution) and idempotency (identical results on repeated execution).

- **Check-Then-Act (TOCTOU) Race Conditions:** Code that first checks for a condition (e.g., `if not resource_exists()`) and then performs an action (e.g., `create_resource()`). A concurrent process can alter the state between the check and the act, leading to duplicate data, errors, or security vulnerabilities. [11, 17, 27, 28]
- **Missing Atomic `UPSERT` Operations:** Application logic that manually implements an `UPSERT` by first reading a record, then deciding whether to `INSERT` or `UPDATE` in separate statements. This is inefficient and prone to race conditions. A single atomic `INSERT ... ON CONFLICT` is safer and more performant. [3, 4, 5, 10]
- **Missing Transactions for Multi-Write Operations:** A sequence of two or more database writes that constitute a single logical unit of work but are not wrapped in a transaction. A failure between writes can leave the database in a permanently inconsistent state. [13, 19]
- **Unsafe Retries on Non-Idempotent Actions:** Retrying operations that have external side effects (e.g., sending an email, charging a card, posting a notification) without a deduplication mechanism like an idempotency key. This can cause duplicate actions, leading to a poor user experience and data corruption. [1, 2, 6, 12, 24]
- **Non-Idempotent DDL in Migrations:** Database migration scripts (`.sql` files) that do not use `IF NOT EXISTS` or `IF EXISTS`. This makes them unsafe to re-run, complicating deployment rollbacks and failure recovery. [8, 15, 16, 18]
- **Read-Modify-Write Race Conditions (Lost Updates):** Code that reads a record (e.g., a JSON object), modifies it in application memory, and writes the entire object back. If two processes do this concurrently, the last writer wins, and the other's changes are lost. Atomic database operations (e.g., `jsonb_set`, `jsonb_insert`) should be used instead. [20, 21, 22, 25, 31]

## Phase 0: Discover project structure

Run the shared **[stack-detection](./stack-detection.md)** pass first. **For this rule, detect the DB/runtime atomicity primitives:** Postgres + psycopg (`bulbul`, `ai/python`) ⇒ interactive transactions (`async with conn.transaction()`), `INSERT ... ON CONFLICT`, and `jsonb_set` apply. Cloudflare D1 (`automations`) ⇒ there are **no interactive transactions** (use `env.DB.batch()` or a Durable Object for cross-statement atomicity), use `INSERT ... ON CONFLICT` / `INSERT OR IGNORE` and `json_set()` (not `jsonb_set`), and queue-consumer idempotency comes from a message-derived key + read-before-write. Do not assume an ORM (`db.query.findFirst`) — both Python and TS use raw SQL. Then add the skill-specific items:

1.  **Identify Database Clients & ORMs:** Scan `package.json`, `pyproject.toml`, and `requirements.txt` for libraries like `psycopg`, `asyncpg`, `sqlalchemy`, `drizzle-orm`, and `prisma`.
2.  **Locate Migration Directories:** Find directories named `migrations`, `drizzle`, or containing `.sql` files.
3.  **Find Queue Consumers & API Clients:** Look for files that define queue workers (e.g., using `celery`, `bullmq`) or make external API calls (e.g., using `httpx`, `axios`), especially those wrapped in retry logic like `tenacity`.

Output the discovered structure before proceeding.

## Phase 1: Audit (parallel agents)

Spawn agents to search their assigned scopes for the following violations.

### Agent assignments

1.  **Check-Then-Act (TOCTOU) Agent:**
    - Scan for sequences of code that check for a resource's existence and then create it in a separate step.
    - **Signature (Python):** `if not await store.get_by_x(...): await store.create(...)`
    - **Signature (TypeScript):** `if (!await db.query.findFirst({ where: ... })) { await db.insert(...); }`
    - **Severity:** High. This is especially critical in API handlers and queue consumers that can run concurrently.

2.  **Missing `UPSERT` Agent:**
    - Scan for logic that manually implements an upsert by fetching an object, then calling `update` or `create` in an `if/else` block.
    - **Signature (Python):** `obj = await store.get(...); if obj: await store.update(...); else: await store.create(...)`
    - **Severity:** Medium. This pattern should be replaced by a single atomic `INSERT ... ON CONFLICT DO UPDATE` statement.

3.  **Missing Transaction Agent:**
    - Scan for methods that perform two or more sequential database write operations (`insert`, `update`, `delete`) without being wrapped in a transaction block.
    - **Signature (Python/psycopg):** Multiple `await cursor.execute(...)` calls for writes within a single method, but without an `async with conn.transaction():` block.
    - **Severity:** High. A failure between writes can leave data in an inconsistent state.

4.  **Unsafe Retry Agent:**
    - Scan for retry logic (e.g., Python's `tenacity` decorator, `try/catch` loops) that wraps non-idempotent actions like API calls that send notifications or create external resources.
    - **Signature:** A queue handler that can be re-executed but calls an external service like `slack.postMessage()` or a payment gateway API without a deduplication key.
    - **Severity:** High. This can lead to duplicate side effects like multiple charges or messages.

5.  **Non-Idempotent DDL Agent:**
    - Scan `.sql` files in migration directories.
    - **Signature:** `CREATE TABLE ...`, `CREATE INDEX ...`, `ALTER TABLE ... ADD COLUMN ...` statements that are missing `IF NOT EXISTS` or `IF EXISTS` clauses.
    - **Severity:** Low. This poses a risk during failed deployments or manual recovery efforts.

6.  **Lost Update Agent (Read-Modify-Write):**
    - Scan for code that fetches a database record containing a `JSONB` column, modifies the deserialized object in Python/TypeScript, and then writes the entire object back.
    - **Signature (Python):** `call = await call_store.get(...); metrics = call.metrics; metrics['new_key'] = val; await call_store.update(call.id, {'metrics': metrics})`
    - **Severity:** Medium. This can lead to data loss under concurrent load.

## Phase 2: Compile findings

After all agents report back, compile a single summary table with columns:

| File | Lines | Violation Pattern | Risk | Severity |
|------|-------|-------------------|------|----------|

Sort by severity (high first), then by file path.

Group the summary into:
- **High Severity** — Check-then-act on unique resources; missing transactions for multi-write operations; unsafe retries on actions with financial or user-visible side effects.
- **Medium Severity** — Missing `UPSERT` patterns; read-modify-write race conditions (lost updates).
- **Low Severity** — Non-idempotent DDL in migration scripts.

## Phase 3: Generate fix plan

For each high-severity finding, output a concrete remediation plan:
- **For Check-Then-Act:** "This pattern is a TOCTOU race condition. Rely on the database's atomicity. Use a `UNIQUE` constraint on the relevant column(s) and handle the potential `UniqueViolation` error in your application. Alternatively, use an atomic `INSERT ... ON CONFLICT DO NOTHING`. For more complex, multi-step checks, use a transaction with `SELECT ... FOR UPDATE` to lock the row(s)." [17, 23, 27]
- **For Missing `UPSERT`:** "This read-then-write pattern is inefficient and prone to race conditions. Replace it with a single atomic database operation. Use `INSERT ... ON CONFLICT (key) DO UPDATE SET ...` to perform the create or update in one step." [3, 5, 10]
- **For Missing Transaction:** "This sequence of writes is not atomic. If an operation fails midway, the system will be in an inconsistent state. Wrap the related `UPDATE`, `INSERT`, and `DELETE` calls in a database transaction (e.g., `async with conn.transaction():` in psycopg) to ensure they all succeed or fail as a single unit." [13, 33]
- **For Unsafe Retry:** "This operation is not idempotent and can cause duplicate side effects on retry. To fix this, pass a unique idempotency key (e.g., a UUID generated by the client) with the request. On the server, before executing the action, check if an action with that key has already been processed. If so, return the previous result instead of re-executing." [1, 6, 7]
- **For Non-Idempotent DDL:** "This migration script will fail if re-run. Add `IF NOT EXISTS` to `CREATE` and `ADD` statements, and `IF EXISTS` to `DROP` statements, to make the migration idempotent and safe for repeated execution." [8, 16]
- **For Lost Updates:** "This read-modify-write pattern can cause lost data under concurrency. Replace it with an atomic database update. For `JSONB` columns in PostgreSQL, use functions like `jsonb_set` or the concatenation operator (`||`) to modify the data directly in the `UPDATE` statement." [20, 21, 22]

Do NOT automatically implement fixes. Present the plan for review and wait for confirmation before making changes.
