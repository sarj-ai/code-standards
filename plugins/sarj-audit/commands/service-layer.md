Audit the codebase for separation of concerns violations. Business logic should live in service classes, service classes should use dependency injection for their dependencies, and controllers/handlers/components should be thin wrappers that delegate to services.

## What to look for

### Business logic outside the service layer

A good codebase keeps business logic in service classes/modules. Flag code where:
- **API route handlers / controllers** contain business logic (validation beyond request parsing, data transformation, conditional branching on business rules, direct database calls)
- **UI components** contain business logic (data fetching, complex state derivation, business rule checks, anything beyond presentation)
- **Utility files** contain business logic that should be a service method (if it depends on external resources or encapsulates a business rule, it's a service, not a utility)
- **Database queries are scattered** — queries appear directly in handlers, components, or scripts instead of being encapsulated in a repository or service

A handler/controller should do: parse request → call service → format response. A component should do: receive props/state → render UI → delegate events to services/stores.

### Missing dependency injection

Service classes should receive their dependencies (database connections, other services, external clients, configuration) via constructor injection or function parameters. Flag code where:
- **Services instantiate their own dependencies** — `new DatabaseClient()` or `import db from './db'` inside a service instead of receiving it as a constructor parameter
- **Hard-coded external resource access** — Services that directly import and use singletons (database pools, HTTP clients, cache connections, message queues) instead of accepting them as injected dependencies
- **Tight coupling between services** — Service A directly imports and instantiates Service B instead of receiving it via injection
- **No interface/type for dependencies** — Injected dependencies lack a type or interface, making it impossible to substitute test doubles

Do NOT flag:
- Pure utility functions with no side effects (these don't need DI)
- Constants, configuration objects, and type imports
- Framework-mandated patterns (e.g., Next.js server actions must be in certain files, Django views follow a specific pattern)
- Simple scripts or CLI tools that aren't part of the application's service architecture
- Code that already uses a DI container or framework (e.g., NestJS, Spring, FastAPI `Depends`, Go `wire`)

### Poor separation of concerns

Flag files or classes that mix multiple responsibilities:
- **A single file that handles HTTP, business logic, and database access** — should be split into handler → service → repository layers
- **God services** — service classes with 10+ public methods or 500+ lines that should be split into focused services
- **Circular dependencies between services** — Service A depends on Service B and vice versa
- **Presentation logic in services** — services that format responses, generate HTML, or know about HTTP status codes
- **Infrastructure in business logic** — business logic that directly references caching, queuing, logging implementation details instead of abstracting them

## Phase 0: Discover project structure

Before spawning audit agents, run a single discovery step:

1. **Detect project type and framework** — Check for Next.js, Express, Fastify, NestJS, Django, Flask, FastAPI, Spring Boot, Rails, Phoenix, Gin, Fiber, Axum, or similar. The framework determines what "thin handler" and "service layer" look like.
2. **Find all source roots** — For monorepos, list each workspace/package. For single-package repos, use the project root.
3. **Map the current architecture** — Identify directories that contain: API routes/controllers, services/business logic, database/repository code, UI components, utilities. Note if the project already has a clear layered structure or not.
4. **Detect DI patterns** — Check if the project uses a DI container (NestJS modules, Spring beans, FastAPI `Depends`, Python `dependency-injector`, Go `wire`/`fx`, etc.) or manual constructor injection.
5. **Detect ORM / database layer** — Check for Drizzle, Prisma, TypeORM, Sequelize, SQLAlchemy, Django ORM, GORM, Diesel, ActiveRecord, Ecto, etc.
6. **Partition into 2–10 agents** — Create one agent per source root or architectural layer. Target 2–10 agents total.

Output the discovered architecture (source roots, framework, DI pattern, database layer, directory structure, agent partitions) before proceeding.

## Phase 1: Audit (parallel agents)

Spawn the agents determined in Phase 0 concurrently. Each agent searches its assigned scope for violations in the three categories above.

### Agent scope guidance

- **API route / controller agents** — Scan handler files. For each handler, check if it contains logic beyond: parse request → call service → format response. Flag any direct database calls, business rule conditionals, or data transformation.
- **Service layer agents** — Scan service files. Check constructor/initialization for hard-coded dependencies. Check method bodies for presentation concerns (HTTP, HTML, response formatting). Check class size and cohesion.
- **Component / view agents** — Scan UI component files. Flag business logic, direct API calls, complex data derivation, or anything beyond presentation and event delegation.
- **Cross-cutting agents** — Look for business logic hiding in middleware, utilities, helpers, scripts, or test fixtures that should be in a service.

Each agent reports: **file path**, **line range**, **violation category** (logic placement, missing DI, separation of concerns), **what the code does**, **where it should live**, **severity** (high = core business logic in wrong layer, medium = minor logic leak, low = borderline case), **effort** (trivial = move function, low = extract to service, moderate = refactor with new interfaces).

## Phase 2: Compile findings

After all agents report back, compile a single summary table:

| File | Lines | Category | Current | Should be | Severity | Effort |
|------|-------|----------|---------|-----------|----------|--------|

Sort by severity (high first), then by effort (trivial first).

Group into:
- **Critical** — Core business logic in handlers/components, services with no DI (high severity, any effort)
- **Important** — Minor logic leaks, missing interfaces for dependencies (medium severity)
- **Cleanup** — Borderline cases, minor improvements (low severity)

Print totals by category and severity.

## Phase 3: Generate refactoring plan

For each critical finding, output a concrete refactoring plan:
- The exact code to extract and where it should move
- The service class/method signature (with injected dependencies as constructor parameters)
- The interface/type for each dependency
- How the handler/component should call the service after refactoring
- Any new files to create

Do NOT automatically implement changes. Present the plan for review and wait for confirmation before making changes.
