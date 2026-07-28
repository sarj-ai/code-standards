Audit the codebase for "magic values"—hardcoded literals that obscure intent and create maintenance hazards. Replace them with named constants, enumerations, or configuration variables to improve readability, maintainability, and type safety.

## What this audits

A "magic value" is a number or string in source code with no explanation. It harms clarity because its purpose is not immediately obvious. It harms maintainability because if the value needs to change, it must be found and updated in multiple places, risking errors.

This audit targets:
- **Unexplained numbers:** Hardcoded numeric literals for timeouts, thresholds, retry counts, status codes, ports, and scaling factors.
- **Unexplained strings:** Hardcoded string literals for configuration keys, model names, user roles, status slugs, API endpoints, and repeated complex patterns like SQL queries.
- **Inadequate type definitions:** Using `str` or `Literal[str, ...]` in Python where a more robust `enum.StrEnum` would be safer and more self-documenting.

**Note:** This audit focuses on objective, automatable patterns. It aims to enforce consistency and make the codebase more self-documenting.

## Phase 0: Discover project structure

Run the shared **[stack-detection](./stack-detection.md)** pass first. **For this rule:** when recommending a fix for stringly-typed sets, never suggest a TypeScript `enum` — `automations` bans it via `@sarj/no-enum`, and the org is zod-first; recommend `z.enum([...])` (zod v4) or an `as const` map instead. On the Python side use `enum.StrEnum`. Then add the skill-specific items:

- Identify Python files using `typing.Literal` with string arguments.
- Identify `.tsx` / `.jsx` files that contain UI components with `className` or `style` props.
- Identify files containing common timer/delay functions (`setTimeout`, `asyncio.sleep`, `timedelta`).

Output the discovered structure before proceeding.

## Phase 1: Audit (parallel agents)

Spawn agents to search their assigned scopes for the following violations in Python and TypeScript files.

### Agent assignments

Each agent will scan for the following concrete patterns derived from reviewer comments:

1.  **Unexplained Numeric Literal (`ruff: PLR2004`, `typescript-eslint: no-magic-numbers`):
    - **Pattern:** Numeric literals (integers or floats), excluding 0 and 1, used directly in comparisons, arithmetic, function arguments, or variable assignments where a named constant would be clearer.
    - **Examples:** `if score > 0.8`, `retries=3`, `status_code=403`, `width * 1.5`.
    - **Action:** Flag any such number not defined as a module-level constant.

2.  **Hardcoded Time Duration:**
    - **Pattern:** Raw numbers used for time intervals in functions like `setTimeout`, `delay`, `timedelta`, or `asyncio.sleep`.
    - **Examples:** `asyncio.sleep(0.5)`, `expires_in * 1000`, `timedelta(hours=1)`, `timeout=900`.
    - **Action:** Flag numeric literals in timer/delay functions, especially those representing non-trivial durations (e.g., > 1 second).

3.  **String or Literal Union Candidate for Enum:**
    - **Pattern (Python):** Type hints using `str` or `typing.Literal` with two or more string values for a parameter that represents a fixed set of choices.
    - **Pattern (TypeScript):** Function arguments or object properties typed as `string` where a string literal union, `enum`, or `as const` object would be more appropriate.
    - **Examples:** `status: Literal["pending", "running"]`, `def validate(status: str)`, `transactionType: z.string()`.
    - **Action:** Flag these definitions as candidates for conversion to a `enum.StrEnum` (Python) or a `const` object / `enum` (TypeScript).

4.  **Hardcoded Configuration String:**
    - **Pattern:** String literals that represent external configuration, identifiers, or environment-dependent values.
    - **Examples:** Model names (`"gemini-1.5-pro"`), API endpoints (`"/api/v1/sessions"`), file paths (`"/tmp/audio.wav"`), or specific identifiers (`"whisper-large-v3-turbo"`).
    - **Action:** Flag string literals used as arguments or in assignments that appear to be configuration.

5.  **Repeated Complex String Literal:**
    - **Pattern:** A long, identical string literal is used in multiple places within the same file.
    - **Examples:** A list of SQL columns (`"id, name, created_at, updated_at"`) repeated in `SELECT` and `RETURNING` clauses.
    - **Action:** Detect string literals longer than 40 characters that appear more than once in a file.

6.  **Hardcoded UI Style Value:**
    - **Pattern:** In `.tsx` files, JSX attributes like `className` with long, complex string literals of CSS utilities, or `style` props with hardcoded hex color values.
    - **Examples:** `className='bg-green-500 hover:bg-green-600 ...'`, `style={{ color: '#FF0000' }}`, `width={80}`.
    - **Action:** Flag `className` attributes with more than 5 space-separated values or `style` attributes with literal color strings or numeric dimensions.

## Phase 2: Compile findings

After all agents report back, compile a single summary table with columns:

| File | Lines | Value | Type | Recommendation | Severity |
|------|-------|-------|------|----------------|----------|

Sort by severity (high first), then by file path.

- **High Severity:** Repeated SQL lists, magic numbers in core logic (e.g., financial calculations, security checks), hardcoded model names.
- **Medium Severity:** Magic strings for configuration, `Literal` types that should be `StrEnum`, hardcoded UI styles.
- **Low Severity:** Magic numbers for timeouts or delays, minor unexplained strings.

## Phase 3: Generate fix plan

For each finding, output a concrete remediation plan. Do NOT automatically implement fixes.

- **For Numeric Literals:** "The number `403` is a magic value. Extract it to a named constant, e.g., `HTTP_FORBIDDEN = 403`, to clarify its meaning."
- **For Time Durations:** "The number `900` represents a timeout. Use a named constant to clarify the unit, e.g., `TOKEN_CACHE_TTL = timedelta(minutes=15)` in Python, or `const TOKEN_CACHE_TTL_MS = 900 * 1000;` in TypeScript."
- **For `Literal` to `StrEnum`:** "The type hint `Literal['internal', 'domestic']` should be a `StrEnum` for better type safety, e.g., `class TransferType(StrEnum): INTERNAL = 'internal'; DOMESTIC = 'domestic'`."
- **For Configuration Strings:** "The string `'gemini-1.5-pro'` is a magic value. Extract it to a named constant or configuration variable, e.g., `DEFAULT_LLM_MODEL = 'gemini-1.5-pro'`."
- **For Repeated SQL Columns:** "The SQL column list `'id, name, ...'` is repeated. Define it as a module-level constant `ORGANIZATION_FIELDS = '...'` and reference it in queries."
- **For UI Styles:** "The `className` `'bg-green-500...'` contains hardcoded styles. Extract these into a component-level `variants` object or a theme file for better maintainability."
