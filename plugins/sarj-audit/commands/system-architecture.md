# System Architecture & Layer Boundaries Audit

Audit the codebase for high-level architectural flaws, improper separation of concerns, missing dependency injection, unoptimized client-server/app-database boundaries, and misaligned data contract tiers.

> [!NOTE]
> This audit focuses exclusively on architectural design decisions requiring system-wide context.
> Deterministic AST issues (such as `stepdown` ordering, `utils.py` naming, AST-detectable raw `env` access, or AST-based missing `await` lists) are enforced by `@sarj/eslint-plugin` and `sarj-python-lint`. Do **not** re-audit deterministic lint rules.

---

## What this audits

### 1. Service Layer & Dependency Injection
- **Leaky Handlers & UI Components**: API route handlers or UI components containing business rules, direct database queries, complex state transitions, or raw external HTTP calls instead of delegating to a dedicated service layer.
- **Hard-Coded Instantiation & Lack of Inversion of Control**: Services or repositories that instantiate their own dependencies internally (e.g., `self.db = DatabaseClient()` or `new StripeClient()`) instead of receiving dependencies via constructor parameters or dependency injection containers.
- **Concrete Dependency Coupling**: High-level business services depending directly on concrete infrastructure classes instead of abstractions (`interface` in TypeScript, `abc.ABC` or `Protocol` in Python), preventing modularity and test double substitution.

### 2. Boundary Logic Pushdown (Client → Server & App → Database)
- **Client → Server Pushdown**: Client-side components (`'use client'` or browser JS) performing manual data fetching (`useEffect`, `useSWR`), client-side list filtering/sorting/derivation of server data, or proxied file uploads through app servers instead of direct-to-storage signed URLs.
- **App → Database Pushdown**: Application code (Python/TypeScript) fetching large datasets into memory to filter, sort, aggregate (`sum`/`avg`), or join in loops, rather than leveraging SQL `WHERE`, `GROUP BY`, `JOIN`, or database computed views.

### 3. Data Contract Tiers & Domain State Modeling
- **Contract Tiers Misalignment**:
  - **Tier 1 (Trust Boundaries)**: HTTP/webhook/RPC endpoints, LLM JSON outputs, external API responses, and database rows MUST use a self-validating schema (`pydantic.BaseModel` or `zod.ZodSchema`) — "Parse, Don't Validate".
  - **Tier 2 (Trusted Internal Records)**: Internal domain objects MUST use `@dataclass(frozen=True, slots=True)` or TypeScript `readonly` types to eliminate unnecessary runtime parsing overhead while maintaining immutability.
  - **Tier 3 (Positional Tuples)**: Reserved for small, positional, unpackable structures (`NamedTuple`).
- **Representing Illegal States**: Models using multiple optional fields (`field_a?: TypeA`, `field_b?: TypeB`) to represent mutually exclusive states instead of discriminated unions (`z.discriminatedUnion` or `typing.Union` with a `Literal` discriminator).

---

## Phase 0: Discover project structure

Run the shared **[stack-detection](./stack-detection.md)** pass first to detect runtime, frameworks, ORM/DB layer, and workspace layout.

Output the discovered architectural layout before proceeding:
- Monorepo vs single-package structure
- Frameworks in use (Next.js, FastAPI, Express, etc.)
- Database layer (psycopg, D1, Drizzle, SQLAlchemy, etc.)
- Component/UI library in use (if applicable)

---

## Phase 1: Audit (parallel agents)

Spawn 3 parallel audit agents:

### Agent 1: Service Layer & Dependency Injection Audit
- Scan API route handlers, controllers, and UI components across all packages.
- Flag handlers/components with embedded business logic, ORM queries, or external API calls.
- Scan service classes for internal `new`/constructor instantiation of infrastructure clients.
- Verify whether dependencies are typed against interfaces/protocols or concrete implementations.

### Agent 2: Client-Server & App-Database Pushdown Audit
- Scan UI component trees for client-side data fetching, post-fetch filtering, or app-server-proxied file uploads.
- Scan application service code for in-memory list filtering/grouping/joining on database query results instead of SQL set operations.
- Identify manual pagination logic that fetches all records instead of using SQL `LIMIT`/`OFFSET` or cursor-based pagination.

### Agent 3: Data Contract Tiers & State Modeling Audit
- Scan system boundaries (API endpoints, webhook handlers, LLM integration points) for raw `dict`/`any`/`unknown` or missing Tier-1 schema validation.
- Identify internal records incorrectly using heavy `BaseModel` parsing where frozen dataclasses belong.
- Identify models with invalid state representations (multiple optionals instead of discriminated unions).

---

## Phase 2: Compile findings

Compile a single summary table:

| Subsystem | File & Lines | Architectural Smell | Impact | Remediation Strategy |
|-----------|--------------|---------------------|--------|----------------------|

Sort by impact (**Critical** > **High** > **Medium**), then by file path.

Group into:
- **Critical Architectural Flaws**: Core business logic trapped in UI/handlers; concrete hardcoded dependencies blocking testing; in-memory processing of un-paginated DB records.
- **High-Impact Improvements**: Missing contract validation at trust boundaries; client-side data fetching/filtering that belongs on the server.
- **Medium / Refactoring**: Replacing heavy internal Pydantic models with frozen dataclasses; converting optional fields to discriminated unions.

---

## Phase 3: Generate refactoring plan

For each Critical and High finding, output a concrete architectural refactoring plan:
1. Exact code to extract and target location in the service layer.
2. New service/repository signatures with constructor-injected interface parameters.
3. Updated SQL query or server action to handle client/app pushdown.
4. Proposed schema / discriminated union definition.

Do NOT automatically apply changes. Present the architectural plan for review.
