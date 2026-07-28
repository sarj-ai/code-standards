Audit the codebase for critical concurrency issues and performance bottlenecks. The goal is to find patterns that negate the benefits of asynchronous programming, lead to inefficient resource use, or create a poor user experience.

## What this audits

This audit targets several categories of defects in Python (`asyncio`) and TypeScript/React applications:

1.  **Concurrency Violations:** Blocking the event loop with synchronous I/O, failing to parallelize independent async operations, and creating unreliable "fire-and-forget" background tasks.
2.  **Performance Bottlenecks:** Inefficient data access patterns (N+1 queries), redundant computations or object creation in hot paths, and suboptimal algorithms (e.g., string concatenation in loops).
3.  **UI Performance:** Unnecessary re-renders in React caused by premature memoization, unstable component definitions, or state updates that block the main thread.

## Phase 0: Discover project structure

Before spawning audit agents, run a single discovery step:

1.  **Detect project type** — Check for monorepo indicators (`pnpm-workspace.yaml`, `turbo.json`, `nx.json`) and primary frameworks (`FastAPI`, `Next.js`, `React`).
2.  **Find all source roots** — Enumerate packages/workspaces containing `src/`, `lib/`, or `app/`.
3.  **Detect languages and file extensions** — Sample files to identify Python (`.py`) and TypeScript (`.ts`, `.tsx`).
4.  **Partition into 2–10 agents** — Create agents partitioned by source root, targeting a balanced load.

Output the discovered structure (source roots, languages, file counts, agent partitions) before proceeding.

## Phase 1: Audit (parallel agents)

Spawn agents to search all Python (`.py`) and TypeScript (`.ts`, `.tsx`) files in their assigned scopes for the following violations.

### Agent Assignments

1.  **Blocking I/O Agent (Python):**
    - In `async def` functions, flag calls to synchronous libraries like `requests`, `time.sleep`, or synchronous database clients (e.g., `boto3` instead of `aioboto3`). These stall the event loop. Cite the `flake8-async` blocking-call rules: `ASYNC210` (blocking HTTP, e.g. `requests`), `ASYNC230` (blocking `open`), `ASYNC251` (blocking `time.sleep`). (Do **not** cite `ASYNC100`/`ASYNC101` — those are cancel-scope/checkpoint rules, unrelated to blocking sync calls.)

2.  **Missing Parallelism Agent:**
    - Find sequences of independent `await` calls on separate lines within the same function. Flag these as opportunities to use `asyncio.gather` (Python) or `Promise.all` (TypeScript) to run the operations concurrently. (Heuristic AST check — **no ruff rule** detects missing parallelism; do not cite one. `RUF024` is `mutable-fromkeys-value`, unrelated.)

3.  **Unhandled Promises & Tasks Agent:**
    - In Python, scan for calls to `asyncio.create_task` where the returned `Task` object is not stored or awaited. This can lead to silently swallowed exceptions. Cite `ruff: RUF006`.
    - In TypeScript, scan for promises that are not `await`ed or chained with `.then()`/`.catch()`. Check for `@typescript-eslint/no-floating-promises` (ESLint-linted packages) or `noFloatingPromises` (Biome-linted packages) — cite whichever the package actually runs (see the stack-detection preamble).

4.  **N+1 Query & Batching Agent:**
    - Scan for loops (`for`, `.map()`) that contain a database query or an API call inside the loop body. This is a classic N+1 problem.
    - Flag these loops and recommend fetching all data in a single bulk query (e.g., `WHERE id IN (...)`) or a single bulk write operation before the loop.

5.  **Redundant Work & Caching Agent:**
    - Flag expensive object instantiations (e.g., `httpx.AsyncClient()`, `re.compile()`, date formatters) inside request handlers, component render functions, or loops. These should be created once at the module level and reused.
    - Flag redundant computations inside loops (e.g., calling `.lower()` on the same string repeatedly) that can be hoisted out.

6.  **Inefficient String Concatenation Agent:**
    - In Python and TypeScript, find loops that build a string using `+=`. This pattern often has O(n^2) complexity.
    - Recommend appending to a list/array and then joining at the end. (Heuristic AST check — **no ruff rule** backs this; `RUF013` is `implicit-optional`, unrelated. Do not cite it.)

7.  **React Performance Agent:**
    - Flag function or object definitions inside a component body that could be moved outside or memoized to prevent re-creation on every render. Cite `eslint: react/no-unstable-nested-components`.
    - Flag state updates that cause blocking UI re-renders and could be wrapped in `useTransition`.
    - Flag overuse of `useMemo` and `useCallback` on simple values or functions where the overhead outweighs the benefit of memoization.

## Phase 2: Compile findings

After all agents report back, compile a single summary table with columns:

| File | Lines | Violation | Severity | Recommendation |
|------|-------|-----------|----------|----------------|

Sort by severity (critical first), then by file path.

Group the summary into:
- **Critical** — Blocking I/O in async functions; Unhandled fire-and-forget tasks.
- **High** — N+1 query patterns; Missing parallelism in hot paths.
- **Medium** — Redundant work in loops/requests; Inefficient string building.
- **Low** — Premature React memoization; Unstable component definitions.

## Phase 3: Generate fix plan

For each finding, output a concrete remediation plan:
- **For Blocking I/O:** "Replace the synchronous call `requests.get()` with its asynchronous equivalent from `httpx`: `await client.get()`. For unavoidable sync code, wrap it with `await asyncio.to_thread(...)`."
- **For Missing Parallelism:** "Combine the sequential `await` calls into a single `await asyncio.gather(...)` (Python) or `await Promise.all([...])` (TypeScript) to execute them concurrently."
- **For Unhandled Tasks/Promises:** "To ensure task completion and handle errors, store the returned task/promise. Either `await` it directly, add it to a collection for a later `gather`/`Promise.all`, or attach error handling with `.catch()`."
- **For N+1 Queries:** "Replace the loop containing database/API calls with a single bulk operation. Fetch all required items at once with a `WHERE id IN (...)` clause or a `get_many(ids)` method before the loop."
- **For Redundant Work:** "Move the initialization of `httpx.AsyncClient()` or `re.compile()` outside the function to a module-level constant so it is created only once."
- **For Inefficient String Concatenation:** "Instead of using `+=` in a loop, append substrings to a list and call `''.join(list)` once at the end for O(n) performance."
- **For React Performance:** "To prevent re-creating functions on every render, move them outside the component or wrap with `useCallback`. For expensive state updates that cause UI lag, wrap the update in `startTransition()` to keep the UI responsive."

Do NOT automatically implement fixes. Present the plan for review and wait for confirmation before making changes.
