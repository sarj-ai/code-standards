---
description: Audit unexplained literals and open-ended values that obscure intent.
---

Audit the codebase for "magic values"—hardcoded literals that obscure intent and create maintenance hazards. Replace them with named constants, validated value sets, or configuration variables to improve readability, maintainability, and type safety.

## What this audits

A "magic value" is a number or string in source code with no explanation. It harms clarity because its purpose is not immediately obvious. It harms maintainability because if the value needs to change, it must be found and updated in multiple places, risking errors.

This audit targets:
- **Unexplained numbers:** Hardcoded numeric literals for timeouts, thresholds, retry counts, status codes, ports, and scaling factors.
- **Unexplained strings:** Hardcoded string literals for configuration keys, model names, user roles, status slugs, API endpoints, and repeated complex patterns like SQL queries.
- **Open-ended type definitions:** Using raw `str` in Python where the surrounding
  logic clearly defines a closed domain. A `Literal["a", "b"]` annotation is already
  a valid closed domain and must not be reported merely because it is not a `StrEnum`.

**Note:** This audit focuses on objective, automatable patterns. It aims to enforce consistency and make the codebase more self-documenting.

## Phase 0: Discover project structure

- Identify raw Python `str` values that are repeatedly compared with a closed set;
  do not report values already constrained by an inline or aliased `Literal[...]`.
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

3.  **Open String Candidate for a Validated Value Set:**
    - **Pattern (Python):** Parameters typed as raw `str` whose implementation repeatedly compares them with two or more fixed string choices. Exclude inline and aliased `Literal[...]` annotations because they already form a closed set.
    - **Pattern (TypeScript):** Function arguments or object properties typed as `string` where a Zod enum, string literal union, or `as const` object would be more appropriate.
    - **Examples:** `def validate(status: str)` followed by comparisons with `"pending"` and `"running"`; `transactionType: z.string()` followed by fixed-value branching.
    - **Action:** Recommend `Literal[...]` or `enum.StrEnum` according to the local-vs-shared runtime needs above; recommend `z.enum([...])` / an `as const` object for TypeScript.

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
- **Medium Severity:** Magic strings for configuration, open-ended strings used as closed domains, hardcoded UI styles.
- **Low Severity:** Magic numbers for timeouts or delays, minor unexplained strings.

## Phase 3: Generate fix plan

For each finding, output a concrete remediation plan. Do NOT automatically implement fixes.

- **For Numeric Literals:** "The number `403` is a magic value. Extract it to a named constant, e.g., `HTTP_FORBIDDEN = 403`, to clarify its meaning."
- **For Time Durations:** "The number `900` represents a timeout. Use a named constant to clarify the unit, e.g., `TOKEN_CACHE_TTL = timedelta(minutes=15)` in Python, or `const TOKEN_CACHE_TTL_MS = 900 * 1000;` in TypeScript."
- **For open string domains:** "This raw `str` is compared with a fixed set of values. Constrain it with `Literal[...]`; use `StrEnum` instead only when callers need a shared runtime enum identity or behavior."
- **For Configuration Strings:** "The string `'gemini-1.5-pro'` is a magic value. Extract it to a named constant or configuration variable, e.g., `DEFAULT_LLM_MODEL = 'gemini-1.5-pro'`."
- **For Repeated SQL Columns:** "The SQL column list `'id, name, ...'` is repeated. Define it as a module-level constant `ORGANIZATION_FIELDS = '...'` and reference it in queries."
- **For UI Styles:** "The `className` `'bg-green-500...'` contains hardcoded styles. Extract these into a component-level `variants` object or a theme file for better maintainability."
