# System Architecture & Layer Boundaries Audit

Audit the codebase for high-level architectural flaws, improper separation of concerns, missing dependency injection, unoptimized client-server/app-database boundaries, DTO entity leakage, sync-to-async queue offloading, and misaligned data contract tiers.

> [!NOTE]
> This audit focuses exclusively on architectural design decisions requiring system-wide context.
> Deterministic AST issues (such as `stepdown` ordering, `utils.py` naming, AST-detectable raw `env` access, or AST-based missing `await` lists) are enforced by `@sarj/eslint-plugin` and `sarj-python-lint`. Do **not** re-audit deterministic lint rules.

---

## What this audits

### 1. Service Layer, Layer Directionality & Dependency Injection
- **Leaky Handlers & UI Components**: API route handlers, controllers, or UI components containing core business rules, direct database queries, complex state transitions, or raw external HTTP calls instead of delegating to a dedicated service layer.
- **Layer Directionality & Module Bypassing**: Upper layers bypassing intermediate layers (e.g., UI components or API handlers directly initializing DB drivers or executing raw SQL), circular dependencies between services, or domain modules depending on infrastructure details.
- **Hard-Coded Instantiation & Lack of Inversion of Control**: Services or repositories instantiating their own dependencies internally (e.g., `self.db = DatabaseClient()` or `new StripeClient()`) instead of receiving dependencies via constructor parameters or dependency injection containers. *(Note: Concrete-class constructor injection via a hand-rolled container like `container.ts` is a valid DI pattern when a single implementation exists; mandate interfaces/protocols only when multiple implementations or test doubles exist).*
- **DTO Entity Leakage & Boundary Over-Exposure**: Returning internal database ORM models or database entities directly as public HTTP responses, exposing internal/sensitive metadata (password hashes, soft-delete flags, tenant IDs) and coupling internal database schemas to public API contracts.

### 2. Boundary Logic Pushdown & Queue Offloading
- **Client → Server Pushdown**: Client-side components (`'use client'` or browser JS) performing manual data fetching (`useEffect`, `useSWR`), client-side list filtering/sorting/derivation of server data, or proxied file uploads through app servers instead of direct-to-storage signed URLs.
- **App → Database Pushdown & N+1 Loops**: Application code (Python/TypeScript) fetching large datasets into memory to filter, sort, aggregate (`sum`/`avg`), or join in loops (`for item in items: db.query(...)`), rather than leveraging SQL `WHERE`, `GROUP BY`, `JOIN`, or set-based batching.
- **Sync-to-Async Queue Offloading**: Synchronous HTTP request handlers executing heavy, long-running processes (PDF generation, heavy image transformation, bulk external API synchronization) directly within the request lifecycle instead of offloading to background job queues (BullMQ, Celery, Workers/Queues).

### 3. Data Contract Tiers & Domain State Modeling
- **Contract Tiers Misalignment**:
  - **Tier 1 (Untrusted Boundaries)**: HTTP/webhook/RPC request payloads, external API responses, webhooks, and LLM JSON outputs MUST use a self-validating schema (`pydantic.BaseModel` or `zod.ZodSchema`) — "Parse, Don't Validate".
  - **Tier 2 (Trusted Internal Records & DB Rows)**: Trusted internal domain records and database query rows MUST use `@dataclass(frozen=True, slots=True)` or TypeScript `readonly` types/interfaces to eliminate unnecessary runtime parsing overhead while maintaining immutability.
  - **Tier 3 (Positional Tuples)**: Reserved for small, positional, unpackable structures (`NamedTuple`).
- **Representing Illegal States**: Models using multiple optional fields (`field_a?: TypeA`, `field_b?: TypeB`) to represent mutually exclusive states instead of discriminated unions (`z.discriminatedUnion` or `typing.Union` with a `Literal` discriminator).

---

## Phase 0: Discover project structure

Run the shared **[stack-detection](./stack-detection.md)** pass first to detect runtime, frameworks, ORM/DB layer, workspace layout, and DI conventions (e.g. `container.ts`).

Output the discovered architectural layout before proceeding:
- Monorepo vs single-package structure
- Frameworks in use (Next.js, FastAPI, Express, etc.)
- Database layer (psycopg, D1, Drizzle, SQLAlchemy, etc.)
- DI style (concrete `container.ts` vs interface abstractions)
- Queue infrastructure (BullMQ, Celery, Cloudflare Queues, etc.)

---

## Phase 1: Audit (parallel agents)

Spawn 3 parallel audit agents:

### Agent 1: Service Layer, Layer Directionality & DI Audit
- Scan API route handlers, controllers, and UI components across all packages.
- Flag handlers/components with embedded business logic, ORM queries, or external API calls.
- Audit layer directionality (prevent UI/API bypassing service layers, detect circular imports).
- Check service constructor dependencies (flag internal `new Client()` instantiation; respect `container.ts` concrete injection).
- Audit API endpoints for DTO entity leakage (direct exposure of database ORM models in responses).

### Agent 2: Boundary Pushdown, N+1 & Queue Offloading Audit
- Scan UI component trees for client-side data fetching, post-fetch filtering, or app-server-proxied file uploads.
- Scan application service code for in-memory list filtering/grouping/joining on database query results instead of SQL set operations.
- Identify N+1 query loops (`for x in list: query(x)`) and manual pagination logic.
- Audit synchronous HTTP handlers executing heavy file/data processing for missing background queue offloading.

### Agent 3: Data Contract Tiers & State Modeling Audit
- Scan untrusted system boundaries (API endpoints, webhook handlers, LLM integration points) for raw `dict`/`any`/`unknown` or missing Tier-1 schema validation.
- Identify internal records or database query rows incorrectly using heavy Tier-1 `BaseModel` parsing where Tier-2 frozen dataclasses belong.
- Identify models with invalid state representations (multiple optionals instead of discriminated unions).

---

## Phase 2: Compile findings

Deduplicate findings across agents and compile a single summary table:

| Subsystem | File & Lines | Architectural Smell | Impact | Remediation Strategy |
|-----------|--------------|---------------------|--------|----------------------|

Sort by impact (**Critical** > **High** > **Medium**), then by file path.

Group into:
- **Critical Architectural Flaws**: Core business logic trapped in UI/handlers; concrete hardcoded dependencies blocking testing; in-memory processing of un-paginated DB records; heavy long-running sync tasks blocking HTTP request threads.
- **High-Impact Improvements**: DTO entity leakage on public API endpoints; missing Tier-1 contract validation at untrusted boundaries; client-side data fetching/filtering that belongs on the server.
- **Medium / Refactoring**: Replacing heavy internal Pydantic models with frozen dataclasses; converting optional fields to discriminated unions.

---

## Phase 3: Generate refactoring plan

For each Critical and High finding, output a concrete architectural refactoring plan:
1. Exact code to extract and target file location in the service layer directory (e.g. `src/services/` or `app/services/`).
2. New service/repository signatures with constructor-injected parameters (honoring `container.ts` or interface abstractions).
3. Updated SQL query, batch fetch, or background queue job worker for offloaded operations.
4. Proposed DTO / response schema / discriminated union definition.

Do NOT automatically apply changes. Present the architectural plan for review.
