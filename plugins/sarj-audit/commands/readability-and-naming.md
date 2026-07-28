Audit the codebase for common smells that harm readability and maintainability. This skill automates the detection of vague names, unhelpful comments, inconsistent conventions, and poor code organization, allowing human reviewers to focus on logic and architecture.

## What this audits

This audit targets several categories of low-hanging fruit for improving code clarity, derived from recurring patterns in human code reviews:

- **Vague Naming:**
    - **Module Names:** Files named `utils.py`, `helpers.ts`, `common.js`. These tend to become dumping grounds for unrelated functions, hiding the code's structure.
    - **Re-export-only Modules:** `index.ts` or `__init__.py` files that only contain re-exports (`export * from '...'` or `from . import ...`), which can obscure module boundaries and complicate dependency analysis.

- **Inconsistent Naming:**
    - **Casing Mismatches:** Using `snake_case` in TypeScript/JSON or `camelCase` in Python, especially in data transfer objects (DTOs) at API boundaries.

- **Unhelpful or Stale Comments:**
    - **Redundant Comments:** Comments that merely state *what* the code is doing, providing no additional context or *why* (e.g., `i += 1 // increment i`). This includes docstrings that just echo type information. [3, 4, 7]
    - **Stale Comments:** Out-of-date comments or documentation that no longer reflect the current state of the code.

- **Poor Code Organization:**
    - **Stepdown Rule Violations:** Defining private helper functions *above* the public functions that call them, forcing readers to scroll up to understand the flow. [10, 12, 13]

- **Overly Complex or "Clever" Code:**
    - Logic that is unnecessarily dense or uses non-obvious language features, making it hard to understand at a glance. This includes complex one-liners, deeply nested conditionals, and confusing expressions.

## Phase 0: Discover project structure

Run the standard discovery pass first to detect project structure, languages, and source roots. Then, add the following skill-specific discovery tasks:

- Identify common data transfer objects (DTOs) by scanning for Pydantic `BaseModel` classes and Zod `z.object` schemas. Pay special attention to files in API, service, or shared type layers.

Output the discovered structure before proceeding.

## Phase 1: Audit (parallel agents)

Spawn agents to search their assigned scopes for the following violations.

1.  **Vague Naming Agent:**
    - Scan all filenames. Flag any file matching `util(s).{py,ts,js}`, `helper(s).{py,ts,js}`, or `common.{py,ts,js}`. [21, 29]
    - Flag `index.ts` and `__init__.py` files that consist primarily of re-export statements (e.g., `export * from ...` or `from . import ...`).

2.  **Inconsistent Naming Agent:**
    - In TypeScript files, scan Zod schemas and other object literals for property names written in `snake_case` and suggest `camelCase`. [1, 18]
    - In Python files, scan Pydantic models for property names written in `camelCase` and suggest `snake_case`.

3.  **Comment Smell Agent:**
    - Flag single-line comments that are a direct translation of the code on the same line (e.g., `x = 5 # Set x to 5`). [4, 5]
    - Flag docstrings or JSDoc where the description is a simple restatement of the function name and parameters (e.g., `/** gets the user by id */ getUserById(id)`). [7, 8]
    - Identify stale comments by extracting identifiers (function/variable names) from comment blocks and checking if they still exist within the file's scope.

4.  **Code Organization Agent:**
    - For each file, build a call graph. Flag instances where a function `A` calls function `B`, but `B` is defined *before* `A` (a "step-up" call). Ignore calls to imported functions or class methods on other objects. [10, 19, 23]

5.  **Complex Code Agent:**
    - Flag nested `if` statements (more than 1 level deep) that can be combined with `and`. [36]
    - Flag complex list/dict comprehensions in Python that are longer than one line or difficult to read, suggesting a rewrite as a clearer, multi-line loop.
    - Flag the use of the walrus operator `:=` inside a complex conditional where a separate assignment line would be clearer.

## Phase 2: Compile findings

After all agents report back, compile a single summary table with columns:

| File | Lines | Smell | Recommendation | Severity |
|------|-------|-------|----------------|----------|

Sort by severity (high first), then by file path.

Group the summary into:
- **High Severity** — Vague filenames (`utils.py`); stepdown violations that invert file flow.
- **Medium Severity** — Inconsistent casing in DTOs; redundant/stale comments.
- **Low Severity** — Re-export-only modules; overly "clever" but functional code.

## Phase 3: Generate fix plan

For each finding, output a concrete remediation plan:
- **For Vague Naming:** "The file `common/utils.ts` has a vague name that encourages it to become a grab-bag of unrelated functions. Rename it to describe its primary responsibility, such as `source-type-detection.ts`."
- **For Inconsistent Casing:** "The Zod schema `MySchema` in `src/schemas.ts` uses `snake_case` for the property `request_id`. In TypeScript, prefer `camelCase` (`requestId`). Use Zod's `.transform()` to map the incoming `snake_case` field to the `camelCase` property on your object."
- **For Redundant Comments:** "The docstring for `get_modal_apps` in `modal_service.py` is redundant as it just repeats the type signature. Remove the docstring. If there is important context about *why* the function exists or potential failure modes, add a comment explaining the *why*, not the *what*."
- **For Stepdown Violations:** "The function `_private_helper` in `main.py` is defined at line 25, but is first called by `public_api_function` at line 50. To follow the Stepdown Rule, move `_private_helper` to be below `public_api_function` so the file reads top-to-bottom."
- **For Complex Code:** "The nested `if` statement at `logic.py:42` can be collapsed into a single `if a and b:` for better readability."
