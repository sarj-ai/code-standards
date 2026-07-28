Audit the codebase for use of primitive or overly-permissive types (`dict`, `list`, `Any`, `object`, `unknown`) where explicit, typed data contracts should be used. The goal is to replace them with schemas (e.g., Pydantic, Zod, dataclasses) to create self-validating data contracts that make illegal states unrepresentable and prevent entire classes of data-related bugs.

## What this audits

This audit targets function signatures, return types, and variable annotations that use weak types for structured data. These are common sources of runtime errors and data corruption. The core principle is "Parse, Don't Validate": data entering a system boundary should be immediately parsed into a strict, typed schema. [3, 8, 9, 12]

- **Overly-permissive types:** Using `dict`, `list`, `tuple` in Python, or `any`/`object` in TypeScript for what should be a well-defined data structure. [2, 7] (Note: `unknown` is the *correct* type for data at a boundary that is about to be parsed — flag it only when it is **not** immediately narrowed by a `.parse()` / type guard.)
- **Unvalidated data boundaries:** Accepting data from external sources (APIs, user input, databases, LLMs) without parsing it against a schema at the point of entry. [1, 6]
- **Stringly-typed data:** Using raw strings for values that belong to a fixed set (e.g., statuses, categories). These should be `Enum`s. [27]
- **Implicit state variants:** Using multiple optional fields to represent states that should be modeled with a discriminated union to make illegal states unrepresentable. [14, 15, 32, 33]

## Phase 0: Discover project structure

Run the standard discovery pass first to partition the codebase. Then add the skill-specific items:

- Scan for imports of `pydantic`, `dataclasses`, and `zod` to identify where data contracts are already in use and establish existing patterns.

Output the discovered structure before proceeding.

### The contract-strength tiers (Python)

Pick the *lightest* contract that makes illegal states unrepresentable — do **not** push everything to `BaseModel`:

- **Tier 1 — trust boundaries** (HTTP/webhook/RPC request bodies, LLM JSON output, DB rows, external API responses): a `pydantic.BaseModel` (or `zod` on the TS side) is **mandatory**. This is the only place runtime parsing/coercion earns its cost — "Parse, Don't Validate."
- **Tier 2 — trusted internal records (the default):** prefer `@dataclass(frozen=True, slots=True)` — immutable, typed, low-memory, and **zero per-instance validation overhead**, so internal hops aren't needlessly re-validated.
- **Tier 3 — `typing.NamedTuple`:** reserve for small, positional, genuinely tuple-shaped values where structural/iterable/unpacking semantics are wanted.

**Do NOT flag** an existing `frozen` dataclass or `NamedTuple` as "missing validation" or "should be a `BaseModel`". Converting an internal record to `BaseModel` **with no new trust boundary** is a non-finding. Only escalate to `BaseModel` when the data actually crosses a boundary.

## Phase 1: Audit (parallel agents)

Spawn agents to search their assigned scopes for the following violations. Each agent should report the file, line number, the problematic code, and a recommended fix.

### Python Agents (`.py`, `.pyi` files)

- **Permissive Primitives and `Any`:** Find function signatures, return types, and variable annotations using `dict`, `list`, `tuple`, or `Any` (including in `dict[str, Any]`) for structured data. These should become a typed contract at the appropriate tier (see "contract-strength tiers" above): `BaseModel` at a boundary, otherwise a `frozen` dataclass / `NamedTuple`. (Ruff: `ANN401` flags `Any` specifically.) [23, 31, 34]
- **Unvalidated Dictionary Access:** Find direct key access on a dictionary that was sourced from an external input (e.g., `request.json()`, `json.loads()`) without first parsing it with a Pydantic model.
- **String Literals Instead of Enums:** Find `str` parameters or fields that are compared against a hardcoded list of string literals (e.g., `if status not in ["active", "inactive"]`). These are candidates for `enum.StrEnum`. (Ruff: `PLR2004`) [16, 24, 27, 38]
- **Missing Discriminated Unions:** Find Pydantic models or dataclasses with multiple `Optional` fields that represent mutually exclusive states. These should be refactored into a `typing.Union` of specific models with a `typing.Literal` discriminator field.
- **Manual Parsing of LLM JSON Output:** Find calls to LLM SDKs that include instructions like "return JSON" in the prompt, followed by a manual `json.loads()` on the response text. These should use the SDK's native structured output feature (`response_schema` or `tools`).

### TypeScript Agents (`.ts`, `.tsx` files)

- **Permissive `any` or `object` Types:** Find function arguments, return types, interfaces, and props typed as `any` or `object`. These hide type information and prevent static analysis. Do **not** flag `unknown` at a boundary that is immediately parsed — that is the correct pattern. (ESLint: `@typescript-eslint/no-explicit-any`; Biome: `noExplicitAny`.) [2, 7, 11, 19, 21]
- **Unvalidated API Responses and Type Assertions:** Find `fetch` calls or API route handlers where the response from `.json()` is cast using `as MyType` without runtime validation. All external data must be parsed with a Zod schema. (ESLint: `@typescript-eslint/no-unsafe-assignment`; no Biome analog — treat as a semantic AST/grep check for `as` on `.json()` results in Biome-linted packages.) [1, 6, 13, 22, 39]
- **String Literal Unions Instead of `z.enum`:** Find `type Status = 'pending' | 'success' | 'failed'` declarations used for data validation. These should be defined as a `z.enum([...])` to be the single source of truth for both static types and runtime parsing.
- **Missing Discriminated Unions:** Find interfaces or types with multiple optional fields representing different states. These should be a `z.discriminatedUnion` to make illegal states unrepresentable. [14, 15, 32, 33, 40]

## Phase 2: Compile findings

After all agents report back, compile a single summary table with columns:

| File | Lines | Problematic Code | Recommendation | Severity |
|------|-------|------------------|----------------|----------|

Sort by severity (high first), then by file path.

Group the summary into:
- **High Severity:** Unvalidated parsing at API/data boundaries; use of `any`/`unknown` for core data models.
- **Medium Severity:** Use of primitives (`dict`, `list`) for internal data structures; string literals that should be enums; missed discriminated unions.
- **Low Severity:** Minor opportunities for stricter typing on internal variables.

## Phase 3: Generate fix plan

For each high-severity finding, output a concrete remediation plan:
- **For a Python `dict` or `Any`:** "Replace the `dict` or `Any` type hint with a typed contract at the right tier. If the value crosses a trust boundary, use a Pydantic `BaseModel` for runtime validation: `class Payload(BaseModel): ...`. If it is a trusted internal record, use `@dataclass(frozen=True, slots=True)` (no validation overhead). Reserve `typing.NamedTuple` for small positional values."
- **For a TypeScript `any`:** "Replace the `any` type with a Zod schema and infer the static type using `z.infer`. This ensures data is validated at runtime. A suggested schema is: `const PayloadSchema = z.object({ ... }); type Payload = z.infer<typeof PayloadSchema>;`" [17, 18]
- **For unvalidated parsing:** "Parse the raw JSON object with a schema immediately upon receipt. Replace `const data = await req.json() as Type` with `const data = TypeSchema.parse(await req.json())`."
- **For string literals:** "Convert these related string constants into a `StrEnum` (Python) or a `z.enum` (TypeScript) to create a single source of truth and prevent typos."
- **For missing discriminated unions:** "Refactor the type to a discriminated union to make illegal states unrepresentable. Replace `{ file?: File; folder?: Folder }` with `type Event = { type: 'file', ... } | { type: 'folder', ... }`."
