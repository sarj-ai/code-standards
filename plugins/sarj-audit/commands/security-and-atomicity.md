# Security & Atomicity Audit

Audit the codebase for cross-tenant authorization leaks (IDOR), missing role-based access controls, insecure session handling, atomicity failures in database operations, and non-idempotent distributed side-effects.

> [!NOTE]
> This audit focuses on complex authorization and concurrency semantics that require deep semantic analysis across multiple layers.
> Deterministic AST rules (such as `no_secret_in_log`, `prefer_constant_time_secret_compare`, `no_cors_wildcard_with_credentials`, or `store_insert_requires_on_conflict`) are enforced by `@sarj/eslint-plugin`, `sarj-python-lint`, and `sarj-sql-lint`. Do **not** re-audit deterministic linter rules.

---

## What this audits

### 1. Tenant Isolation & Authorization (AuthN/AuthZ)
- **IDOR via Missing Tenant Predicates**: Database or store methods fetching, updating, or deleting records by primary key (`WHERE id = %s`) without scoping by the caller's tenant (`organization_id`, `tenant_id`, or `user_id`).
- **Admin Operations Missing Role Checks**: Destructive or administrative endpoints (role changes, tenant deletion, financial operations) protected only by basic authentication rather than explicit role checks (`require_admin`, `require_superadmin`).
- **Client-Controlled Subject IDs**: API endpoints accepting `user_id` or `organization_id` in request bodies or query parameters instead of strictly deriving identity from the verified session/token on the server.
- **Client-Side-Only Permissions**: UI components hiding actions based on user roles where the corresponding backend API endpoint lacks matching server-side permission checks.

### 2. Atomicity, Idempotency & Distributed Concurrency
- **Check-Then-Act (TOCTOU) Race Conditions**: Code checking for resource existence (`if not store.get(...)`) before executing a creation/update step in a separate statement, creating race condition windows under concurrent load.
- **Missing Multi-Write Transaction Boundaries**: Sequences of multiple database write operations (`INSERT`, `UPDATE`, `DELETE`) representing a single logical unit of work executed outside an explicit database transaction (`async with conn.transaction()`).
- **Unsafe Retries on Non-Idempotent Actions**: Background queue workers or API clients retrying operations with external side-effects (payment charges, emails, webhooks, notifications) without enforcing deduplication keys or idempotency tokens.
- **Read-Modify-Write Lost Updates**: Application code reading a JSON/JSONB document or record into memory, modifying attributes in JS/Python, and writing the full object back, overwriting concurrent edits.

---

## Phase 0: Discover project structure

Run the shared **[stack-detection](./stack-detection.md)** pass first.

Identify tenancy and database primitives:
- Tenancy model (`organization_id`, `workspace_id`, `user_id`, or single-tenant)
- DB transaction capability (Interactive PostgreSQL transactions vs D1 `env.DB.batch()` batching)
- Authentication & Session verification framework

---

## Phase 1: Audit (parallel agents)

Spawn 2 parallel audit agents:

### Agent 1: Tenant Isolation & Authorization Audit
- Enumerate all store/repository methods and verify every read/write query filters by tenant context.
- Audit administrative and destructive API endpoints for role checks.
- Audit API payload contracts for client-supplied subject IDs (`user_id`/`organization_id`).
- Cross-check UI role checks against backend route protection.

### Agent 2: Atomicity & Concurrency Audit
- Scan for TOCTOU check-then-act sequences across data handlers and background tasks.
- Scan for multi-statement DB writes missing interactive transaction wrappers.
- Audit retry policies (`tenacity`, queue retries) wrapping non-idempotent external calls.
- Scan for read-modify-write patterns on complex JSONB fields.

---

## Phase 2: Compile findings

Compile a single summary table:

| Domain | File & Lines | Defect / Vulnerability | Risk | Remediation Strategy |
|--------|--------------|------------------------|------|----------------------|

Sort by risk (**Critical** > **High** > **Medium**), then by file path.

Group into:
- **Critical Security & Integrity Risks**: IDOR tenant leaks; missing admin role checks; missing multi-write transactions; un-deduplicated external side-effects on retry.
- **High Risk**: Client-controlled subject IDs in request bodies; TOCTOU race conditions; read-modify-write lost updates.
- **Medium Risk**: Client-side permission checks missing backend enforcement.

---

## Phase 3: Generate remediation plan

For each Critical and High finding, output a concrete fix plan:
1. Exact SQL predicate / tenant filter to add (`AND organization_id = %s`).
2. Required role dependency to attach to route handler (`Depends(require_admin)`).
3. Session refactor to derive identity from token instead of request body.
4. Transaction boundary wrapper or atomic SQL `INSERT ... ON CONFLICT` statement.
5. Idempotency key implementation for external side-effects.

Do NOT automatically apply changes. Present the plan for review.
