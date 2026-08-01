Audit the codebase for opportunities to enforce a clear separation of concerns, pushing logic from the client to the server and from the application layer to the database.

## Phase 0: Discover project structure

Before spawning audit agents, run a single discovery step:

1.  **Detect project type** — Check for monorepo indicators: `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `lerna.json`, or a `workspaces` field in the root `package.json`. For single-package repos, use the project root.
2.  **Find all source roots** — For monorepos, list each workspace/package with a `src/` or `lib/` directory. For single-package repos, use the project root.
3.  **Detect UI framework & SSR support** — Check for Next.js (`next.config.*`), Nuxt (`nuxt.config.*`), SvelteKit (`svelte.config.*`), Remix (`remix.config.*`), or Astro (`astro.config.*`). If a framework with strong server-side capabilities is not detected, the "Client → Server" audit concern is less applicable.
4.  **Detect ORM / database layer** — Check dependencies for `drizzle-orm`, `prisma`, `typeorm`, `sequelize`, `knex`, `kysely`, or raw SQL files. If no database layer is detected, the "Application → Database" audit concern is not applicable.
5.  **Detect lint/build/typecheck commands** — Read `package.json` scripts across all source roots to find commands for `lint`, `build`, and `typecheck` for later verification.

Output the discovered structure (source roots, framework, database layer) and which audit concerns are applicable before proceeding.

## Phase 1: Audit (parallel agents)

Based on what Phase 0 discovered, spawn agents for **only the applicable concerns** below. Each agent searches **all source roots** and should return a structured report with: file path, line numbers, current approach, suggested fix, impact (high/medium/low), and effort (trivial/low/moderate).

### Concern 1: Client → Server Logic *(only if SSR framework detected)*

Search for logic in client-side code (`'use client'` components, hooks) that should be moved to the server. Modern frameworks like Next.js provide powerful server-side capabilities that should be leveraged to improve performance, security, and maintainability. [4, 6]

-   **Client-Side Data Fetching**: Client components using hooks like `useEffect`, `useState`, or `useSWR` to fetch data. This data should be fetched in an `async` Server Component and passed down as props. [2, 4, 6]
    -   **Signature**: Look for `useEffect(() => { fetch(...) }, [])` or `useSWR('/api/...')` inside components marked with `'use client'`. The presence of `useState` for loading and error states is also a strong indicator.
-   **Manual Client-Side State After Mutations**: Using `useState` to manually manage UI state after a mutation (e.g., deleting an item from a list), instead of relying on server-driven data revalidation.
    -   **Signature**: An event handler that calls a server action or API endpoint, followed by a `setState` call to manually alter the local data array (e.g., `setItems(items.filter(i => i.id !== deletedId))`). The correct pattern is to use a Server Action with `revalidatePath()` to trigger a server-side data refresh. [7, 10, 16, 17]
-   **Unnecessary API Routes**: Creating dedicated API routes (e.g., `app/api/.../route.ts`) for simple mutations or data fetching that are better handled by Next.js Server Actions or direct data access in Server Components. [1, 3, 5, 9]
    -   **Signature**: A `POST` or `PUT` handler in an API route file that is called by a `fetch` in a client component, where a `<form action={...}>` with a server action would be simpler and more integrated. [1, 8]
-   **Client-Side Data Transformation**: Performing data mapping, filtering, sorting, or complex calculations (`.map`, `.filter`, `.reduce`, `useMemo`) on the client with data that originates from the server.
    -   **Signature**: Find `useMemo` hooks or direct calls to `.filter()`, `.sort()`, or `.reduce()` on props that hold lists of data from the server. This logic should be moved to the server, preferably into the database query itself.
-   **Proxied File Uploads**: API endpoints that accept raw file bodies (e.g., from `FormData`) and stream them to object storage. This should be replaced with a pre-signed URL pattern where the client uploads directly to storage. [11, 12, 13, 27]
    -   **Signature**: A server action or API route (in Next.js or FastAPI) that reads a file from the request body and uploads it to GCS/S3. The correct pattern is an endpoint that *generates* a signed URL for the client to use for a direct upload. [19, 20, 22]
-   **Frontend-Defined Business Logic**: Hardcoding business rules, constants, or validation logic on the client-side.
    -   **Signature**: Look for hardcoded constants (e.g., `SARJ_ORG_ID`), complex validation logic, or data mappings (e.g., mapping slugs to display names) in client components. This logic should originate from the backend to ensure consistency and security.

### Concern 2: Application → Database Logic *(only if ORM/database detected)*

Search for data processing in the application layer (TypeScript/Python) that should be pushed down into the database query. Databases are highly optimized for set-based operations. [21, 23, 25, 28]

-   **Post-Fetch Filtering and Aggregation**: Fetching a large list of records and then filtering, sorting, or aggregating them in application code.
    -   **Signature**: A database query that returns a list, immediately followed by `.filter()`, `.reduce()`, or a `for` loop that calculates a sum/average. This should be replaced with `WHERE`, `GROUP BY`, `SUM()`, `AVG()`, etc., in the SQL query. [21, 28]
-   **Application-Level Defaults**: Checking for `null` or `undefined` in fetched data and replacing it with a default value.
    -   **Signature**: Code like `const value = data.field ?? 'default';` or `if (x is None): x = 0`. This can be replaced with `COALESCE(field, 'default')` in the SQL query.
-   **Manual Pagination Logic**: Implementing `hasMore` or `totalPages` logic in the application by fetching all records or by checking if `results.length === limit`. This is inefficient, especially with large offsets. [35, 36, 37, 39]
    -   **Signature**: The pagination state is calculated based on the returned array. The better pattern is to query for `limit + 1` records and use the presence of the extra record to determine if a next page exists, avoiding expensive `COUNT(*)` queries or large offsets. [40]

## Phase 2: Prioritize

After all agents report back, compile a priority table sorted by impact/effort ratio:

| File | Lines | Current Approach | Suggested Fix | Impact | Effort | Concern |
|------|-------|------------------|---------------|--------|--------|---------|

Group into:
-   **High impact, low effort** — Implement immediately
-   **Medium impact** — Implement if time allows
-   **Low impact or high effort** — Note for future

## Phase 3: Implement

Work through the priority list top-to-bottom:
1.  Make each change.
2.  After each batch of related changes, run the `lint`, `build`, and `typecheck` commands discovered in Phase 0 to verify correctness.
3.  Commit all changes with a descriptive commit message, referencing the audit.
