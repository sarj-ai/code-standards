Audit the codebase for violations of separation of concerns, dependency injection, and abstraction principles. Business logic should live in service classes, services should receive their dependencies via injection, and controllers/handlers/components should be thin wrappers that delegate to services.

## What to look for

### 1. Business Logic in API Route Handlers

API route handlers (e.g., in FastAPI, Next.js) should be thin. Their only job is to parse the request, call a single service method, and format the response. Flag handlers that contain business logic, such as:
- Direct database queries or ORM calls (`db.query(...)`, `prisma.user.create(...)`).
- Complex data transformation or validation logic beyond basic request shape.
- Conditional branching based on business rules.
- Direct calls to external services (`httpx.get(...)`, `fetch(...)`).
- High cyclomatic complexity (e.g., `ruff: C901` or `eslint: complexity` violations).

### 2. Hard-Coded Dependency Instantiation

Classes should receive their dependencies through their constructor (constructor injection), not create them internally. This is fundamental to inversion of control (IoC) and makes code testable and modular. Flag code where:
- A class instantiates another class inside its `__init__` or `constructor`: `self.db = DatabaseClient()`.
- A method creates its own client for a one-off call: `client = boto3.client('s3')`.
- A class directly imports and uses a global or singleton instance: `import db_connection`.

### 3. Missing Abstraction for Dependencies

Dependencies should be defined by abstractions (interfaces in TypeScript, Abstract Base Classes in Python), not concrete implementations. This allows for interchangeable components and easy mocking in tests, following the Dependency Inversion Principle. [1, 4, 5] Flag code where:
- A class constructor requires a concrete class: `constructor(repo: PsqlUserRepo)` instead of `constructor(repo: IUserRepo)`.
- A function signature requires a specific implementation, making it hard to test without the real dependency.
- A core service or repository is defined as a concrete class with no corresponding `interface` or `abc.ABC`.

### 4. Business Logic in UI Components

UI components (e.g., React) should focus on presentation. Complex state management and business logic make them brittle and hard to test. Flag components that:
- Fetch their own data directly within `useEffect` instead of using a dedicated service or custom hook.
- Contain complex state derivation, business rule validation, or data manipulation.
- Have many `useState` hooks and event handlers that could be consolidated into a custom hook (`useMyComponentLogic`). [14, 21, 34]

### 5. Layering & Separation of Concerns (SoC) Violations

Code should be organized into distinct layers (e.g., API, services, data access) with clear boundaries. Flag violations where:
- A data access layer (store/repository) knows about higher-level concepts like object storage or HTTP. It should only deal with database operations.
- A service layer knows about presentation details like HTTP status codes or response formatting.
- A library/shared package depends on an application-level package or environment variables.
- A client for one service (e.g., a bank API client) contains logic related to another service (e.g., LiveKit). [12, 13]

## Phase 0: Discover project structure

Before spawning audit agents, run a single discovery step:

1.  **Detect project type and framework** — Check for Next.js, Express, NestJS, Django, Flask, FastAPI, etc. This determines what a "thin handler" and "service layer" look like.
2.  **Map the current architecture** — Identify directories for API routes/controllers, services/business logic, database/repository code, and UI components. Note if a clear layered structure exists.
3.  **Detect DI patterns** — Check for DI containers (NestJS modules, Spring beans, FastAPI `Depends`, Python `dependency-injector`) or manual constructor injection.
4.  **Detect ORM / database layer** — Check for Prisma, Drizzle, SQLAlchemy, Django ORM, etc.
5.  **Partition into 2–10 agents** — Create one agent per architectural layer (e.g., `api-routes-agent`, `services-agent`, `ui-components-agent`).

Output the discovered architecture before proceeding.

## Phase 1: Audit (parallel agents)

Spawn the agents determined in Phase 0. Each agent searches its assigned scope for the violations described in "What to look for."

### Agent scope guidance

-   **API route / controller agents** — Scan handler files. For each handler, check if it contains logic beyond: parse request → call one service method → format response. Flag any direct database calls, business rule conditionals, or complex data transformations.
-   **Service layer agents** — Scan service files. Check constructors for hard-coded dependencies (`new Client()`). Check methods for presentation concerns (HTTP knowledge) or infrastructure concerns (direct file I/O, environment variable access).
-   **Repository / store agents** — Scan data access files. Flag any logic that is not direct data querying (e.g., calling external APIs, complex business rule enforcement).
-   **Component / view agents** — Scan UI component files. Flag business logic, direct API calls, or complex state management that could be extracted to a custom hook or service.

Each agent reports: **file path**, **line range**, **violation category**, **what the code does**, **where it should live**, **severity**, and **effort**.

## Phase 2: Compile findings

After all agents report back, compile a single summary table:

| File | Lines | Category | Current | Should be | Severity | Effort |
|------|-------|----------|---------|-----------|----------|--------|

Sort by severity (high first), then by effort (trivial first).

Group into:
-   **Critical** — Core business logic in handlers/components; services instantiating their own dependencies.
-   **Important** — Minor logic leaks; missing interfaces for dependencies.
-   **Cleanup** — Borderline cases; minor improvements.

## Phase 3: Generate refactoring plan

For each critical finding, output a concrete refactoring plan:
-   The exact code to extract and where it should move.
-   The new service class/method signature, with injected dependencies as constructor parameters.
-   The `interface` or `abc.ABC` for each new dependency.
-   How the handler/component should be updated to call the new service.
-   Any new files to create.

Do NOT automatically implement changes. Present the plan for review.
