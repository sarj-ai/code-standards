Launch parallel agents to audit the codebase for opportunities to replace hand-rolled code with well-maintained third-party libraries. The goal is to find places where a mature npm package would drastically reduce code, improve reliability, and lower maintenance burden.

## What to look for

A good candidate for replacement is code that:
- Reimplements functionality available in a popular, well-maintained library
- Contains edge-case handling that a battle-tested library already covers
- Would shrink by 50%+ lines if replaced with a library call
- Sits in a domain where getting it wrong has real consequences (dates, crypto, parsing, validation)

Do NOT flag:
- Thin wrappers around platform APIs (e.g., a 5-line fetch wrapper)
- Code that is intentionally minimal to avoid dependency bloat
- Cases where the library would be larger than the code it replaces
- UI components already using a component library (that's covered by sarj-ts-audit-stack)

## Phase 0: Discover project structure

Before spawning audit agents, run a single discovery step:

1. **Detect project type** — Check for monorepo indicators: `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `lerna.json`, or a `workspaces` field in the root `package.json`. For single-package repos, use the project root.
2. **Find all source roots** — For monorepos, list each workspace/package with a `src/` or `lib/` directory. For single-package repos, use the project root.
3. **Inventory existing dependencies** — Read all `package.json` files to build a list of already-installed packages. This prevents agents from suggesting libraries already in use.
4. **Detect runtime constraints** — Check for edge runtime indicators (`next.config.js` with `runtime: 'edge'`, Cloudflare Workers `wrangler.toml`, Deno `deno.json`). Some libraries don't work in all runtimes — agents must respect these constraints.
5. **Detect UI framework** — Check if the project uses React, Vue, Svelte, Angular, or none. This determines whether agents 8–9 (React patterns, form patterns) are relevant.

Output the discovered structure (source roots, dependency list, runtime constraints, UI framework) before proceeding.

## Phase 1: Audit (parallel agents)

Spawn the following 10 agents concurrently. Each agent must:

1. Search **all source roots** discovered in Phase 0 (not hardcoded paths)
2. Identify hand-rolled logic that a well-known library handles better
3. Cross-check against the dependency inventory — don't suggest a library that's already installed unless it's installed but unused in the relevant code
4. For each finding, report: **file path**, **line range**, **what the code does**, **suggested library** (with npm package name), **estimated line reduction**, **confidence** (high = drop-in replacement, medium = minor refactor needed, low = significant restructuring), and **runtime compatibility** (works everywhere, Node-only, browser-only)

### Agent assignments

1. **Date/time handling** — Search for hand-rolled date parsing, formatting, comparison, duration calculation, or timezone logic. Suggest `date-fns`, `dayjs`, or `temporal-polyfill` where appropriate.

2. **String manipulation & formatting** — Search for hand-rolled slug generation, email sanitization, URL parsing, template string builders, pluralization, or text truncation. Suggest libraries like `slugify`, `validator`, `url-parse`, or `pluralize` where they'd help.

3. **Array/collection operations** — Search for complex array transformations: manual groupBy, unique, chunk, flatten, intersection, difference, sorting with multiple keys, or deep merge. Suggest `remeda`, `lodash-es` (specific imports), or native alternatives.

4. **HTTP/API client patterns** — Search for repeated fetch patterns with retry logic, error handling, timeout, rate limiting, or request queuing. Suggest `ky`, `ofetch`, or `p-retry` / `p-queue` where a few lines would replace dozens.

5. **File & data format handling** — Search for hand-rolled CSV parsing, JSON schema validation beyond Zod, MIME type detection, base64 encoding/decoding, or binary data manipulation. Suggest `papaparse`, `mime-types`, or similar.

6. **Async patterns** — Search for hand-rolled concurrency control (batched Promise.all, semaphores, debounce, throttle, retry with backoff, polling loops). Suggest `p-limit`, `p-retry`, `p-queue`, `p-debounce`, or similar.

7. **Crypto & hashing** — Search for hand-rolled UUID generation, hash computation, token generation, or comparison. Check if existing implementations could use `nanoid`, `uuid`, or Web Crypto API more effectively.

8. **UI component patterns** — *Skip this agent if no UI framework was detected in Phase 0.* Search component files for hand-rolled hooks or patterns that established libraries handle (intersection observer, media queries, clipboard, keyboard shortcuts, local storage). Suggest framework-appropriate libraries (e.g., `@uidotdev/usehooks`, `react-hotkeys-hook` for React; `@vueuse/core` for Vue).

9. **Form & validation patterns** — *Skip this agent if no UI framework was detected in Phase 0.* Search for hand-rolled form state management, multi-step form logic, or complex validation chains beyond basic Zod. Suggest framework-appropriate solutions (e.g., `react-hook-form`, `conform` for React; `vee-validate` for Vue).

10. **Error handling & logging** — Search for hand-rolled error boundary patterns, structured logging, error serialization, or retry/fallback chains. Suggest `serialize-error`, `pino`, or similar lightweight options.

## Phase 2: Compile findings

After all agents report back, compile a single summary table:

| File | Lines | Current approach | Suggested library | Line reduction | Confidence | Runtime |
|------|-------|-----------------|-------------------|----------------|------------|---------|

Sort by estimated line reduction (highest first), then by confidence (high first).

Group into:
- **High confidence, high reduction** — clear wins, should adopt
- **Medium** — worth considering, may need evaluation
- **Low confidence or low reduction** — note for future

Print total estimated line reduction across all findings.

## Phase 3: Recommend

For each high-confidence finding:
- Show the current code snippet (abbreviated)
- Show what it would look like with the library
- Note any concerns (bundle size, runtime compatibility, maintenance status)
- Flag if the library is Node-only and the code runs in an edge/browser runtime

Do NOT automatically implement changes. Present the recommendations for review and wait for confirmation before making changes.
