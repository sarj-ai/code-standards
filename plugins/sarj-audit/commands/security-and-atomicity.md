# Security & Atomicity Audit

Audit the codebase for cross-tenant authorization leaks (IDOR), missing role-based access controls, privilege escalation via payload pollution, atomicity failures in database operations, and non-idempotent distributed side-effects.

> [!NOTE]
> This audit focuses on complex authorization and concurrency semantics that require deep semantic analysis across multiple layers.
> Deterministic AST rules (such as `no_secret_in_log`, `prefer_constant_time_secret_compare`, `no_cors_wildcard_with_credentials`, or `store_insert_requires_on_conflict`) are enforced by `@sarj/eslint-plugin`, `sarj-python-lint`, and `sarj-sql-lint`. Do **not** re-audit deterministic linter rules.

---

## What this audits

### 1. Tenant Isolation & Authorization (AuthN/AuthZ)
- **IDOR via Missing Tenant Predicates**: Database or store methods fetching, updating, or deleting records by primary key (`WHERE id = %s`) without scoping by the caller's tenant (`organization_id`, `tenant_id`, or `user_id`).
- **Nested Parent-Child Ownership Leaks**: Endpoints accessing nested resources (e.g. `/orgs/:orgId/projects/:projId`) that filter `projId` by `orgId` parameter without verifying that `orgId` itself belongs to the caller's verified session tenant.
- **Admin Operations Missing Role Checks**: Destructive or administrative endpoints (role changes, tenant deletion, financial operations) protected only by basic authentication rather than explicit role checks (`require_admin`, `require_superadmin`).
- **Client-Controlled Subject IDs & Unverified Headers**: API endpoints accepting `user_id` or `organization_id` in request bodies/query parameters, or trusting unverified HTTP headers (`X-User-Id`, `X-Organization-Id`) instead of strictly deriving identity from the verified session/token on the server.
- **Vertical Privilege Escalation via Payload Pollution**: Update endpoints (`PATCH /users/me` or `PUT /account`) accepting user-supplied request models that include sensitive fields (`role`, `is_admin`, `tenant_id`, `permissions`) without strict server-side field filtering.
- **Client-Side-Only Permissions**: UI components hiding actions based on user roles where the corresponding backend API endpoint lacks matching server-side permission checks.
- **Tenant Cache Key Isolation**: Redis or in-memory caching logic using raw resource IDs (`cache:project:123`) instead of tenant-prefixed cache keys (`cache:org:456:project:123`), enabling cross-tenant cache pollution.

### 2. Atomicity, Idempotency & Distributed Concurrency
- **Check-Then-Act & Check-Then-Decrement Race Conditions**: Code checking for resource existence (`if not store.get(...)`) or balance/quota sufficiency (`if balance >= amount`) before executing a write in a separate statement. Quota/balance operations MUST use atomic conditional SQL updates (`UPDATE ... SET balance = balance - :amount WHERE balance >= :amount`).
- **Missing Multi-Write Transaction Boundaries**: Sequences of multiple database write operations (`INSERT`, `UPDATE`, `DELETE`) representing a single logical unit of work executed outside an explicit database transaction (`async with conn.transaction()`).
- **External Network Calls Inside Transactions**: Long-running HTTP/API requests executed inside open database transactions, which holds DB locks, degrades connection pools, and risks duplicate external side-effects on transaction retries.
- **Unsafe Retries on Non-Idempotent Actions**: Background queue workers or API clients retrying operations with external side-effects (payment charges, emails, webhooks, notifications) without enforcing deduplication keys or idempotency tokens.
- **Read-Modify-Write Lost Updates & OCC**: Application code reading a record into memory, modifying attributes in JS/Python, and writing the full object back. Lost updates MUST be prevented using atomic database operations or Optimistic Concurrency Control (OCC) with a `version` / `updated_at` column (`UPDATE ... SET val = :val, version = version + 1 WHERE id = :id AND version = :expected_version`).

---

## Phase 0: Discover project structure

Run the shared **[stack-detection](./stack-detection.md)** pass first.

Identify tenancy and database primitives:
- Tenancy model (`organization_id`, `workspace_id`, `user_id`, or single-tenant)
- DB transaction capability (Interactive PostgreSQL transactions vs D1 `env.DB.batch()` batching)
- Authentication & Session verification framework
- Caching layer (Redis, Cloudflare KV, etc.)

---

## Phase 1: Audit (parallel agents)

Spawn 2 parallel audit agents:

### Agent 1: Tenant Isolation & Authorization Audit
- Enumerate all store/repository methods and verify every read/write query filters by tenant context.
- Audit nested resource access (`/orgs/:orgId/items/:itemId`) for cross-tenant leakage.
- Audit administrative endpoints for role checks and update payloads for privilege escalation (`PATCH /me` with `role`).
- Audit API payload contracts and headers for client-supplied subject IDs (`user_id`/`organization_id`, `X-User-Id`).
- Cross-check UI role checks against backend route protection, and check Redis cache keys for tenant prefixes.

### Agent 2: Atomicity & Concurrency Audit
- Scan for TOCTOU check-then-act and check-then-decrement balance/quota logic (enforce atomic `UPDATE ... WHERE balance >= X`).
- Scan for multi-statement DB writes missing interactive transaction wrappers.
- Detect external network HTTP calls made *inside* open database transaction blocks.
- Audit retry policies (`tenacity`, queue retries) wrapping non-idempotent external calls.
- Scan for read-modify-write patterns and verify Optimistic Concurrency Control (`version` checks) or atomic DB operations.

---

## Phase 2: Compile findings

Deduplicate findings across agents and compile a single summary table:

| Domain | File & Lines | Defect / Vulnerability | Risk | Remediation Strategy |
|--------|--------------|------------------------|------|----------------------|

Sort by risk (**Critical** > **High** > **Medium**), then by file path.

Group into:
- **Critical Security & Integrity Risks**: IDOR tenant leaks; payload pollution privilege escalation; missing admin role checks; missing multi-write transactions; un-deduplicated external side-effects on retry.
- **High Risk**: Client-controlled subject IDs / unverified headers; TOCTOU & non-atomic balance decrements; external HTTP calls inside open DB transactions; read-modify-write lost updates without OCC.
- **Medium Risk**: Client-side permission checks missing backend enforcement; un-isolated cache keys.

---

## Phase 3: Generate remediation plan

For each Critical and High finding, output a concrete fix plan:
1. Exact SQL predicate / tenant filter to add (`AND organization_id = %s`).
2. Required role dependency to attach to route handler (`Depends(require_admin)`).
3. Payload schema refactor to exclude sensitive role/tenant fields on user update routes.
4. Transaction boundary wrapper or atomic conditional SQL update (`UPDATE ... WHERE balance >= :amount`).
5. External HTTP call extraction to execute *outside* transaction blocks.
6. Idempotency key implementation or Optimistic Concurrency Control (`version` column check).

Do NOT automatically apply changes. Present the plan for review.
