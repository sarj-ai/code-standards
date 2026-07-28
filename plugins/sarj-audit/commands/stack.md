Launch parallel agents to audit the codebase for opportunities to move logic down the stack — pushing work from client to server, from application code to SQL, and from raw markup to component-library primitives.

## Phase 0: Discover project structure

Before spawning audit agents, run a single discovery step:

1. **Detect project type** — Check for monorepo indicators: `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `lerna.json`, or a `workspaces` field in the root `package.json`. For single-package repos, use the project root.
2. **Find all source roots** — For monorepos, list each workspace/package with a `src/` or `lib/` directory. For single-package repos, use the project root.
3. **Detect UI framework & SSR support** — Check for Next.js (`next.config.*`), Nuxt (`nuxt.config.*`), SvelteKit (`svelte.config.*`), Remix (`remix.config.*`), Astro (`astro.config.*`), or other frameworks with server component / SSR support. If the framework doesn't support server components or SSR, the "client → server" audit concern is not applicable.
4. **Detect component library** — Check dependencies for `@shadcn/ui` (or a `components/ui/` directory), `@mui/material`, `@chakra-ui/react`, `@mantine/core`, `vuetify`, `radix-ui`, `@headlessui/react`, or similar. If no component library is detected, the "raw HTML → component library" audit concern is not applicable.
5. **Detect ORM / database** — Check dependencies for `drizzle-orm`, `prisma`, `@prisma/client`, `typeorm`, `sequelize`, `knex`, `kysely`, `pg`, `mysql2`, `better-sqlite3`, or similar. Check for raw SQL files. If no database layer is detected, the "app → SQL" and "schema audit" concerns are not applicable.
6. **Detect lint/build/typecheck commands** — Read `package.json` scripts across all source roots. Find the commands for `lint`, `build`, `typecheck` / `tsc`, and `test`. Record these for use in Phase 3.

Output the discovered structure (source roots, framework, component library, database layer, available commands) and which audit concerns are applicable before proceeding.

## Phase 1: Audit (parallel agents)

Based on what Phase 0 discovered, spawn agents for **only the applicable concerns** below. Each agent searches **all source roots** — not hardcoded paths. Each agent should return a structured report with: file path, line numbers, current approach, suggested fix, impact (high/medium/low), and effort (trivial/low/moderate).

### Audit concerns

**1. Client → server** *(only if SSR/server-component framework detected)*

Search for client-side logic that could be precomputed on the server:
- Client components doing data filtering, sorting, or derivation that could happen in a server component or loader
- `useEffect` or `onMounted` fetching data that could be a server-side prop/loader
- Client-side date formatting, array transformation, or string processing on data that comes from the server

Spawn 1 agent per source root that contains component files, or merge small roots. Target 2–5 agents for this concern.

**2. App logic → SQL** *(only if ORM/database detected)*

Search service files, server actions, API routes, and data-access layers for:
- N+1 queries (sequential fetches in loops that could be a single JOIN or IN clause)
- JS-side filtering/grouping/sorting that could be SQL WHERE/GROUP BY/ORDER BY
- Multiple sequential queries that could be consolidated into a single query with JOINs
- Manual data enrichment that could be a database view or computed column

Spawn 1 agent per source root that contains service/data-access files, or merge small roots. Target 1–3 agents for this concern.

**3. Raw HTML → component library** *(only if component library detected)*

Search component files for raw HTML elements that should use the project's component library:
- `<select>`, `<input>`, `<button>` instead of the library's Select, Input, Button
- Hand-rolled modal/dialog, toast/alert, dropdown, tooltip, or accordion patterns
- `<div>` with class patterns that replicate Card, Badge, Avatar, or other library primitives
- Inconsistent styling that the component library would standardize

Spawn 1 agent per source root that contains component/view files, or merge small roots. Target 2–5 agents for this concern.

**4. Schema audit** *(only if ORM/database detected)*

Examine the database schema and all query patterns for:
- Missing indexes on columns used in WHERE, JOIN, or ORDER BY clauses
- Redundant queries that fetch the same data in nearby code paths
- Schema improvements (missing constraints, denormalization opportunities) that would enable the SQL optimizations found by concern 2
- Queries that could benefit from database-level defaults or computed columns

Spawn 1 agent for this concern (it needs a holistic view of the schema).

## Phase 2: Prioritize

After all agents report back, compile a priority table sorted by impact/effort ratio:

| File | Lines | Current | Suggested | Impact | Effort | Concern |
|------|-------|---------|-----------|--------|--------|---------|

Group into:
- **High impact, low effort** — implement immediately
- **Medium impact** — implement if time allows
- **Low impact or high effort** — note for future

## Phase 3: Implement

Work through the priority list top-to-bottom:
1. Make each change
2. After each batch, run the lint and build commands discovered in Phase 0
3. Verify no type errors or regressions
4. Commit all changes with a descriptive commit message
