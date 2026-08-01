Launch parallel agents to audit the codebase for places where TypeScript types are defined manually but could be derived from Zod schemas (or where Zod schemas should be introduced) for better type safety, single source of truth, and runtime validation.

## What to look for

Good candidates for conversion:
- Manual TypeScript type/interface when a Zod schema already exists or should exist
- `as const` arrays with separate type definitions instead of `z.enum()` + `z.infer`
- Duplicate type definitions across files (one could be the Zod-inferred source of truth)
- Manual data validation (if/else, switch, typeof) instead of `z.safeParse()`
- Request/response types without corresponding Zod schemas (missing runtime validation)
- `Record<string, ...>` where `z.record()` or a discriminated union would be safer
- String literal unions that could be `z.enum()` values
- Manual type guards that duplicate what a Zod schema `.parse()` would provide

Do NOT flag:
- Types already derived via `z.infer<typeof schema>` (correct pattern)
- ORM-inferred types like Drizzle `$inferSelect` / Prisma generated types (correct pattern)
- Simple utility types, generics, or mapped types that don't represent data shapes
- Types used only internally within a single function (overhead not justified)
- Component prop types that don't cross a trust boundary

## Phase 0: Discover project structure

Before spawning audit agents, run a single discovery step:

1. **Detect project type** — Check for monorepo indicators: `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `lerna.json`, or a `workspaces` field in the root `package.json`. For single-package repos, use the project root.
2. **Find all source roots** — For monorepos, list each workspace/package with a `src/` or `lib/` directory. For single-package repos, use the project root.
3. **Inventory Zod usage** — Search for `import.*from.*zod` or `require.*zod` across all source roots. Count how many files use Zod and where schemas are concentrated. If Zod is not used at all, note this — the audit will focus on where it *should* be introduced.
4. **Detect alternative validation libraries** — Check dependencies and imports for `yup`, `valibot`, `arktype`, `superstruct`, `io-ts`, `runtypes`, or `joi`. If the project uses a different validation library instead of Zod, adapt all suggestions to use that library's equivalents (e.g., `yup.InferType` instead of `z.infer`, `valibot.parse` instead of `z.parse`).
5. **Detect lint/build/typecheck commands** — Read `package.json` scripts across all source roots. Find the commands for `lint`, `build`, `typecheck` / `tsc`, and `test`. Record these for use in Phase 4.

Output the discovered structure (source roots, Zod usage stats, alternative validation library if any, available commands) before proceeding.

## Phase 1: Discover structure

Have one agent map the codebase structure: list all source roots (from Phase 0), find where schemas/types/services/API routes live, and identify which files already use the validation library. Share this map with all audit agents.

## Phase 2: Audit (parallel agents)

Spawn agents to cover the following **concerns** (not directories — each agent searches all source roots for its concern):

1. **Enum-like patterns** — Find `as const` arrays, string literal unions, and manual enum types. Check if each has a corresponding schema or should get one.

2. **API boundary validation** — Find all API route handlers, server actions, RPC endpoints, and webhook handlers. Check if every request body/params/query is schema-parsed (not manually destructured or cast).

3. **Service layer types** — Find service classes/functions that accept or return data shapes. Check if those shapes have schemas for validation at the boundary.

4. **Config & constants** — Find configuration objects, feature flags, environment variable access, and constant registries. Check if these have schemas ensuring valid shape at startup.

5. **Cross-file type duplication** — Find types defined in multiple places that represent the same concept. Identify which should be the single schema-derived source of truth.

6. **Manual type guards & validation** — Find `typeof`, `instanceof`, `in` operator checks, and switch statements that validate data shape. Check if a discriminated union or `.safeParse()` would be cleaner.

7. **Unsafe casts** — Find `as` assertions and `!` non-null assertions on data from external sources (API responses, DB results, user input). Check if schema parsing would make these safe.

Each agent reports: **file path**, **line range**, **current approach**, **suggested pattern** (using the project's validation library), **impact** (high/medium/low), **effort** (trivial/low/moderate).

## Phase 3: Compile & prioritize

Compile a single summary table sorted by impact (high first), then effort (trivial first):

| File | Lines | Current | Suggested | Impact | Effort |
|------|-------|---------|-----------|--------|--------|

Group into:
- **Quick wins** — high impact, trivial effort (just add inferred type or replace manual type)
- **Worth doing** — create schema, infer type, replace manual validation
- **Future** — low impact or high effort

## Phase 4: Implement

Work through findings top-to-bottom. After each batch, run the lint and typecheck commands discovered in Phase 0 to verify correctness. Commit with a descriptive message.
