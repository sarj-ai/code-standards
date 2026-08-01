Audit the codebase for violations of the "stepdown rule" (newspaper metaphor). Every file should read top-to-bottom: exported/public functions first, then the helpers they call, then the helpers those helpers call, and so on.

## The stepdown rule

A file follows the stepdown rule when:
- Exported / public functions appear at the **top** of the file (below imports and type/constant declarations)
- Each function only calls functions defined **below** it, never above
- Private / helper functions are ordered so that a helper appears **immediately below** the first function that calls it
- Reading the file top-to-bottom reveals intent before implementation, like a newspaper article

A file **violates** the stepdown rule when:
- Helper functions are defined **above** the exported functions that use them
- Exported functions are buried at the **bottom** of the file
- You must scroll **up** to find a function that is called lower in the file
- A cluster of private helpers sits at the top, with the public API at the bottom

**Note:** Top-level constants, type aliases, schemas, interfaces, and class/struct declarations are **not** violations. They are declarations, not logic, and belong at the top alongside imports. Only flag function ordering issues.

## Phase 0: Discover project structure

Before spawning audit agents, run a single discovery step:

1. **Detect project type** — Check for monorepo indicators: `pnpm-workspace.yaml`, `turbo.json`, `nx.json`, `lerna.json`, or a `workspaces` field in the root `package.json`. Also check for non-JS project files: `Cargo.toml`, `go.mod`, `pyproject.toml`, `build.gradle`, `pom.xml`, `*.sln`, `Gemfile`, `mix.exs`.
2. **Find all source roots** — For monorepos, list each workspace/package with a `src/` or `lib/` directory. For single-package repos, use the project root. For non-JS projects, find the conventional source directories (e.g., `src/`, `lib/`, `app/`, `cmd/`, `internal/`, `pkg/`).
3. **Detect languages and file extensions** — Sample files across source roots to determine which languages are in use (`.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.go`, `.rs`, `.java`, `.kt`, `.rb`, `.ex`, `.swift`, etc.). Record the relevant extensions for each source root.
4. **Partition into 2–10 agents** — Create one agent per source root. If a source root has more than ~200 files, split it by subdirectory. If a source root has fewer than ~20 files, merge it with an adjacent root. Target 2–10 agents total.

Output the discovered structure (source roots, languages, file counts, agent partitions) before proceeding.

## Phase 1: Audit (parallel agents)

Spawn the agents determined in Phase 0 concurrently. Each agent must:

1. List all source files matching the detected language extensions in its assigned scope
2. For each file with more than one function declaration, check whether the ordering satisfies the stepdown rule
3. Report violations with: **file path**, **line numbers of the misplaced function(s)**, **what calls what**, **current order vs correct order**, and **severity** (high = exported function buried below helpers, medium = helper defined above its caller, low = minor reordering opportunity)

### Scope guidance

When describing each agent's scope, use these categories to help agents understand what to look for:

- **Service / business logic files** — Files containing exported functions or class methods that implement business rules. Helpers and private methods should follow the public API.
- **Component / view files** — Files exporting UI components (React, Vue, Svelte, templates, etc.). Internal sub-components, event handlers, and data-transform functions should appear below the primary exported component.
- **API route / controller files** — Files defining HTTP handlers, RPC endpoints, or CLI commands. Handler helpers (parsing, validation, transformation) should appear below the exported handler.
- **Page / layout / entry files** — Top-level entry points (pages, layouts, main functions). Setup helpers and data-fetching functions should appear below the entry point.
- **Library / utility files** — Shared utility modules. Exported functions at the top, internal helpers below.

## Phase 2: Compile findings

After all agents report back, compile a single summary table with columns:

| File | Lines | Issue | Severity | Suggested reorder |
|------|-------|-------|----------|-------------------|

Sort by severity (high first), then alphabetically by file path.

Group the summary into:
- **High severity** — Exported functions buried below helpers; file reads bottom-up
- **Medium severity** — Some helpers above their callers but exported functions are near the top
- **Low severity** — Minor reordering would improve readability

Print the total count of violations found, broken down by severity and by source root.

## Phase 3: Generate fix plan

For each high-severity violation, output a concrete reordering plan:
- The exact function names and their current line ranges
- The proposed new order (list function names top-to-bottom)
- Any dependencies between functions that constrain the ordering

Do NOT automatically implement fixes. Present the plan for review and wait for confirmation before making changes.
