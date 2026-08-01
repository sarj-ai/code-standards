Launch parallel agents to audit the codebase for places where attributes, properties, or loosely typed dictionaries are accessed implicitly (e.g. `attributes.get("sip.phoneNumber")`) instead of explicitly defining and validating them through Pydantic (Python) or Zod (TypeScript).

## What to look for

Good candidates for conversion:
- `dictionary.get("key.path")` or `dictionary["key"]` where the dictionary represents structured entity data without a schema.
- Context objects (`ctx`, `request`, etc.) where `.attributes` or `.meta` is accessed loosely instead of being validated.
- `JSON.parse` or similar dynamic payloads being read via loose property access without schema validation.
- Missing Pydantic models for nested JSON objects in Python.
- Missing Zod schemas for nested properties in TypeScript.
- Fallback logic (e.g. `if not number: ...`) that should be handled by schema defaults or validation rules.

Do NOT flag:
- Generic configuration dictionaries where arbitrary keys are expected and a rigid schema is impossible.
- Simple standard library structures (e.g. standard headers parsing) where full object mapping isn't feasible.
- Places where the data has already been validated through `.parse()` or `.model_validate()`.

## Phase 0: Discover project structure

Before spawning audit agents, run a single discovery step:

1. **Detect language and framework** — Check if it's Python (look for `pydantic` in `requirements.txt`/`pyproject.toml`) or TypeScript (look for `zod` in `package.json`).
2. **Find all source roots** — Identify `src/`, `app/`, `lib/` directories where business logic resides.
3. **Inventory loose accesses** — Search for `.get("`, `["`, and `.attributes` to find hotspots where untyped dictionaries or objects are being traversed.

## Phase 1: Audit (parallel agents)

Spawn agents to cover the following **concerns** across the source roots:

1. **Context and Event Objects** — Find event handlers, webhooks, or agents where `ctx.attributes` or `event.payload` is accessed dynamically.
2. **Database and API Responses** — Find places where raw JSON from DB or APIs is accessed without first passing through a Pydantic model / Zod schema.
3. **Configuration and State** — Find arbitrary untyped state dictionaries being passed around and queried loosely.

Each agent reports: **file path**, **line range**, **current approach**, **suggested pattern** (using Pydantic for Python or Zod for TS), **impact** (high/medium/low), **effort** (trivial/low/moderate).

## Phase 2: Compile & prioritize

Compile a single summary table sorted by impact (high first), then effort (trivial first):

| File | Lines | Current | Suggested | Impact | Effort |
|------|-------|---------|-----------|--------|--------|

## Phase 3: Implement

Work through findings top-to-bottom. After each batch, run the standard format and lint commands for the project to ensure correct syntax and types. Commit with a descriptive message.
