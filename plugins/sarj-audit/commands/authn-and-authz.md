Audit the codebase for common authentication and authorization vulnerabilities. This skill is derived from a corpus of review comments that repeatedly flagged insecure-by-default patterns: routes missing authentication, queries that don't filter by the caller's tenant (`organization_id`), admin operations without role checks, and client-controlled subject IDs.

## What this audits

This audit focuses on concrete, high-severity vulnerabilities derived from the review corpus:

- **Missing Authentication:** API routes that should be protected but lack any authentication dependency, making them publicly accessible.
- **Insecure Direct Object Reference (IDOR):** Data store queries that fetch records by a primary key (`id`) without also filtering by the current user's `organization_id`, allowing cross-tenant data access. [1, 3, 5, 7]
- **Missing Role-Based Access Control (RBAC):** Administrative operations (e.g., deleting data, changing roles) that are accessible to any authenticated user because they lack a specific `admin` or `superadmin` role check. [27, 34, 41]
- **Client-Controlled Subject ID (Mass Assignment):** API endpoints that accept an `organization_id` or `user_id` from the request body, allowing an attacker to perform actions on behalf of another entity. [2, 15, 24, 36, 38]
- **Client-Side-Only Permissions:** Security-sensitive UI elements that are hidden on the frontend based on user role, but the backend API they call does not re-verify that permission, allowing bypass via direct API calls. [8, 22, 28, 30]
- **Weak Authentication Mechanisms:** Use of non-constant-time comparisons for secrets (timing attacks), or authentication based on easily spoofed inputs like `User-Agent` headers or email domain names. [11, 12, 16, 17, 20]
- **Insecure Token Handling:** Storing tokens insecurely or failing to properly manage their lifecycle, such as by omitting expiration checks. [4, 6, 10, 19]

## Phase 0: Discover project structure

Run the shared **[stack-detection](./stack-detection.md)** pass first. **Critically for this rule: detect tenancy** — grep the schema/migrations for `organization_id`/`tenant_id`/`workspace_id`. If present (e.g. `bulbul`), the IDOR/ownership-scoping checks below apply in full. If absent (e.g. single-tenant `automations`), **skip the multi-tenant IDOR concern** and instead scope on whatever ownership column exists (token, `user_id`). Also detect the SQL placeholder style (`?` for D1/SQLite vs `%s` for psycopg). Then add the skill-specific items:

1.  **Find route/handler entry points:** Catalog every place that defines an HTTP endpoint (e.g., Python/FastAPI files with `@router.get`, TypeScript/Next.js files in `app/**/route.ts`).
2.  **Find the auth dependency:** Identify how the codebase declares "this route needs auth" (e.g., FastAPI's `Depends(require_authentication)`, Next.js's `await currentUser()`).
3.  **Find the data-store layer:** Locate modules that read/write the database (e.g., files matching `*store.py` or `*repository.ts`).
4.  **Partition into agents:** Create one agent per major API router, service, or frontend area.

Output the discovered structure before proceeding.

## Phase 1: Audit (parallel agents)

Each agent should scan its assigned scope for the following corpus-derived patterns. Report each finding with file path, line number, the specific defect, and severity.

### 1. IDOR via Missing Tenant Predicate (High Severity)
- **Task:** Scan all functions in the data store layer (`*store.py`, etc.). Look for functions that retrieve or mutate a single record by its primary key.
- **Violation:** A function like `get(id: str)` or `delete(id: str)` that takes an ID but *not* an `organization_id` or equivalent tenant identifier. The underlying SQL query's `WHERE` clause filters only on the primary key (`WHERE id = %s`), creating a cross-tenant access vulnerability. [1, 3]
- **Detection:** Find methods in store files that accept an `id` parameter. Analyze the database query to confirm the `WHERE` clause lacks an `AND organization_id = %s` predicate.

### 2. Admin Operations Missing Role Checks (High Severity)
- **Task:** Identify routes that perform sensitive or destructive actions (e.g., deleting resources, changing roles, transferring ownership).
- **Violation:** A route handler for an administrative action is protected only by a basic authentication check (e.g., `Depends(require_authentication)`) instead of a specific role-based check (e.g., `Depends(require_super_admin)`). [9, 13, 14, 21]
- **Detection:** Search router files for routes with names containing `delete`, `update`, `admin`, `rotate`. Check their dependency list for a role-specific check. Flag if absent.

### 3. Client-Controlled Subject ID in Request (High Severity)
- **Task:** Review the Pydantic models, TypeScript interfaces, or input arguments for API route handlers that create or update resources.
- **Violation:** An endpoint accepts `user_id`, `organization_id`, or `creator_id` from the client in the request body or query parameters. The subject's identity must always be derived from the trusted session/token on the server side. [2, 15, 24, 36, 38]
- **Detection:** Scan Pydantic models or request body interfaces. Flag any model used as a request body that contains `user_id` or `organization_id`.

### 4. Missing Authentication on Sensitive Route (High Severity)
- **Task:** Enumerate all API route handlers.
- **Violation:** A route handler that mutates data or returns sensitive information is missing any auth dependency. Exemptions are explicitly public routes like `/health`, `/login`, or webhook handlers (which must have signature verification instead).
- **Detection:** For each route, check its function signature or decorator list for a call that resolves to an auth check. Flag if absent.

### 5. Client-Side-Only Permission Enforcement (Medium Severity)
- **Task:** Find permission checks in frontend code and verify they are mirrored on the backend.
- **Violation:** A UI component uses a check like `user.role === 'admin'` to conditionally render a button, but the backend API it calls does not perform the same check. [8, 22, 28, 30]
- **Detection:** First, find frontend files (`.tsx`, `.vue`) with role checks. Note the API endpoint called. Second, find the backend route handler for that endpoint and confirm it contains an equivalent server-side role check. Flag if the backend check is missing.

### 6. Weak or Spoofable Authentication (Medium Severity)
- **Task:** Look for authentication logic that relies on weak or easily forged inputs.
- **Violation:** The codebase uses non-constant-time string comparison (`==`) for secrets, authenticates based on a `User-Agent` header, or grants permissions based on an email domain check. [11, 12, 17, 20]
- **Detection:** Grep for `key ==`, `token ==` on sensitive values. Search for auth logic that reads `request.headers.get('User-Agent')`. Search for `.endswith('@company.com')` checks used for authorization.

### 7. Insecure Token Handling (Medium Severity)
- **Task:** Review how authentication tokens are stored, validated, and managed.
- **Violation:** Database queries for tokens lack an expiration check (e.g., `AND expires_at > NOW()`). Tokens are stored as unsalted hashes or in plaintext. Session lifetime is excessively long or indefinite. [4, 6, 10, 19]
- **Detection:** Analyze token validation queries in data stores. Inspect session configuration for inactivity and absolute timeouts. Check hashing logic for use of salts.

## Phase 2: Compile findings

After all agents report back, compile a single summary table sorted by severity, then by file path:

| File | Lines | Category | Defect | Severity |
|---|---|---|---|---|

Group the summary into:
- **High Severity:** IDOR, Missing Role Checks, Client-Controlled Subject ID, Missing Authentication.
- **Medium Severity:** Client-Side-Only Permissions, Weak/Spoofable Auth, Insecure Token Handling.

## Phase 3: Generate fix plan

For each high-severity violation, output a concrete remediation plan:
- **IDOR:** The store function to fix and the SQL predicate or ORM filter to add (e.g., `AND organization_id = %s`).
- **Missing Role Check:** The route handler to fix and the specific dependency to add (e.g., `Depends(require_admin)`).
- **Client-Controlled ID:** The field to remove from the request model and the server-side code to replace it (e.g., `organization_id=user.organization_id`).
- **Missing Authentication:** The route handler to fix and the auth dependency to add.

For each violation, propose a regression test that proves the fix (e.g., "a request with a token from a different org returns 403, not 200"). Do NOT automatically implement fixes.
