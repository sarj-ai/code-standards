# Shared Phase-0: Stack detection (run before any audit)

These audit rules target **more than one stack**. The single biggest source of false
positives is assuming one stack's tooling/runtime everywhere. Before applying any
rule, detect the stack of the code under audit and **gate dialect-specific checks on
what you find** — do not flag a pattern that is correct for that repo's runtime, or
cite a linter/rule the repo does not run.

## The known Sarj stack archetypes (verify, don't assume)

| Dimension | Flagship product (Postgres + dbmate) | Internal Workers app (Cloudflare D1) | ML services repo (Postgres + dbmate) |
|---|---|---|---|
| Python web | FastAPI | — (TypeScript only) | FastAPI |
| TS runtime | Next.js 16 SSR (on Cloudflare) | Cloudflare Workers + Hono | — |
| Database | **PostgreSQL 18** | **Cloudflare D1 / SQLite** | PostgreSQL |
| Query layer | raw `psycopg` (no ORM) | raw D1 `.prepare().bind()` | psycopg / SQLAlchemy |
| Migrations | **dbmate** (`-- migrate:up/down`) | **wrangler d1** (append-only, no down) | dbmate |
| TS lint | **ESLint 9** + `typescript-eslint` strict | **Biome** (+ scoped `@sarj` ESLint in one app) | — |
| Python lint | ruff `select=ALL` + **pyright** strict | — | ruff `select=ALL` |
| Logging | **loguru** | `console.log(JSON.stringify(...))` | loguru |
| Tenancy | **multi-tenant** (`organization_id` FK on every table) | **single-tenant** (token/`user_id` scoping) | varies |
| Auth | **Clerk + JWT + roles** | single shared admin bearer token | service tokens |
| Tests | pytest (xdist) + vitest | vitest | pytest |
| CI / IaC | GitHub Actions + **Cloud Build + Docker + Terraform** | GitHub Actions (deploy on merge) | GitHub Actions |
| zod | v4 (`^4.3.6`) | v4 | — |

This table is a **starting hypothesis**, not ground truth — re-detect per run (repos
drift). Detect each dimension from the repo itself:

- **DB dialect** → grep migrations + driver deps: `psycopg`/`pg`/Postgres image ⇒ Postgres; `[[d1_databases]]` in `wrangler.toml` / `.prepare().bind()` ⇒ D1/SQLite.
- **Migration tool** → `-- migrate:up` blocks ⇒ dbmate (has down-migrations); `migrations/*` under `wrangler.toml` ⇒ wrangler d1 (append-only — do **not** flag a missing down-migration).
- **TS lint authority** → `biome.json` ⇒ cite Biome rule names (`noExplicitAny`, `noFloatingPromises`, …); `eslint.config.*` / `typescript-eslint` ⇒ cite ESLint rule names. Never cite an ESLint rule for a Biome-only package or vice-versa.
- **Tenancy** → grep schema for `organization_id` / `tenant_id` / `workspace_id`. Present ⇒ IDOR/ownership-scoping checks apply. Absent ⇒ **skip** the multi-tenant IDOR concern and note single-tenancy (scope on whatever ownership column exists instead).
- **Python logger** → `loguru` ⇒ `logger.exception()` (no `exc_info=` kwarg); stdlib `logging` ⇒ `exc_info=True` is valid.
- **zod major** → read the installed version from the lockfile/catalog, not the range. v4 ⇒ `.loose()`/`.looseObject()` (not `.passthrough()`), two-arg `z.record(K, V)`, `z.enum([...])` for fixed sets.
- **Already-enforced rules** → if the repo runs ruff `select=ALL` or a strict ESLint/Biome config, do **not** re-report what CI already blocks; surface only gaps beyond it.
- **CI / IaC present?** → Terraform/Cloud Build/Dockerfiles present (e.g. the flagship product) ⇒ IaC + container + action-pinning checks apply; absent ⇒ skip them.

## Respect deliberate conventions (do NOT flag)

- The internal Workers app bans TS `enum` via `@sarj/no-enum` — never recommend a TS `enum`; recommend `z.enum([...])` / `as const` maps.
- SQLite booleans as `INTEGER` (0/1) and validation via Zod/`CHECK` rather than native types are intentional on D1.
- `.optional().default('')` fail-safe env defaults and `BooleanFlagSchema` transforms are intentional.
- Concrete-class constructor injection via a hand-rolled `container.ts` is the chosen DI style — do not demand an interface per dependency.
- An `eslint-disable`/`noqa`/`biome-ignore` that carries a documented rationale is a decision, not a finding.

Output the detected stack (per source root) before proceeding to Phase 1.
