Audit the codebase for dead, duplicated, and unnecessary code. The goal is to improve maintainability, reduce cognitive overhead, and prevent bugs that arise from inconsistent updates to duplicated logic. A clean codebase is easier and safer to change.

## What this audits

This audit targets several forms of code cruft that accumulate over time, based on patterns observed in human code reviews:

- **Zombie Code:** Large blocks of commented-out logic that clutter the codebase and lose context. Version control is the source of truth for historical code.
- **Unused Code:** Functions, classes, variables, imports, and entire files that are never referenced. This also includes code that is logically unreachable (e.g., after a `return` statement).
- **Duplicated Logic:** Identical or nearly-identical blocks of code that violate the DRY (Don't Repeat Yourself) principle. This is a major source of bugs when one copy is updated and the other is forgotten.
- **Unnecessary Abstractions:** Redundant helper functions, wrappers around standard library calls, or derived state that add boilerplate without providing value.
- **Reinventing the Wheel:** Hand-rolled implementations of standard functionality already provided by the language's standard library or an approved third-party package.

## Phase 0: Discover project structure

Run the standard discovery pass first to detect project structure and partition agents. Then, add the skill-specific items:

1.  **Identify and configure analysis tools** based on detected languages:
    - **Python:** Prepare to use `ruff` (for rules like `F401` unused-import, `F841` unused-variable, `ERA001` commented-out-code), and `vulture` for cross-file dead code analysis. (Note: ruff has **no** general unreachable-code rule; `B012` is `jump-statement-in-finally`, a different defect — do not cite it for dead/unreachable code.) [5, 11, 12, 23, 28]
    - **TypeScript/JavaScript:** Prepare to use `knip` (for unused files, exports, and dependencies), `jscpd` (for code duplication), and the `tsc` compiler (for `noUnusedLocals`, `noUnusedParameters`, `allowUnreachableCode`). [1, 3, 10, 14]
2.  **Prepare for duplication analysis:** Ready a code similarity detection approach (e.g., using `jscpd` or a custom token-based scanner) to find duplicated code blocks across the codebase. [3, 17, 21]

Output the discovered structure (source roots, languages, file counts, agent partitions, and planned tooling) before proceeding.

## Phase 1: Audit (parallel agents)

Spawn agents to search their assigned scopes for the following violations. For each finding, report the file, line numbers, a description of the issue, and a recommended fix.

1.  **Zombie Code (Commented-out Logic)**
    - **Signature:** Large, contiguous blocks of commented-out code, especially entire functions or classes. Look for more than 3 consecutive lines starting with `#` or `//`, or multi-line `/* ... */` blocks containing logic.
    - **Rationale:** Commented-out code clutters the codebase and quickly becomes outdated. Version control is the correct place to store historical code. This is often flagged with comments like "can we delete this?" or "just delete stuff instead of commenting it out".
    - **Tooling:** Use regex-based searches. Ruff's `ERA001` also identifies this.

2.  **Unused Imports and Variables**
    - **Signature:** Imports or local variables that are defined but never referenced.
    - **Rationale:** Dead code increases cognitive load, can hide bugs, and adds to maintenance overhead. These are the most common and easily fixed issues.
    - **Tooling:**
        - For Python, use `ruff` (`F401` for imports, `F841` for variables). [12, 23, 37, 39]
        - For TypeScript, use `tsc --noUnusedLocals` and `tsc --noUnusedParameters` or the equivalent `@typescript-eslint/no-unused-vars` rule. [1, 6, 25, 26, 31]

3.  **Unused Functions, Classes, and Files**
    - **Signature:** Functions, classes, or entire files that are never referenced from any other part of the codebase.
    - **Rationale:** This represents significant dead weight, increasing the surface area for maintenance and potential bugs without providing any value. Reviewers often ask "do we still need this?" or note that a file is "defined but never used".
    - **Tooling:**
        - For Python, use `vulture` for a deep, cross-file analysis of unused functions and classes. [5, 11, 15, 28]
        - For TypeScript, use `knip` to find unused files, exports, and dependencies. [10, 14, 18, 22]

4.  **Duplicated Logic (DRY Violations)**
    - **Signature:** Identical or nearly-identical blocks of code (>5 lines) appearing in multiple locations. This includes copy-pasted helper functions, validation logic, or data transformations.
    - **Rationale:** Duplication is a major source of bugs when one copy is updated and the other is forgotten. Review comments often point this out with "can we reuse the core business logic in the spirit of DRY?" or "why duplicate in two places?".
    - **Tooling:** Use a code similarity detection tool like `jscpd`. [3, 17, 19, 21]

5.  **Unreachable or Redundant Code Paths**
    - **Signature:** Code that appears after a non-conditional `return`, `raise`, or `throw` statement. Also, `if/else` or `match/case` blocks where multiple branches contain identical code.
    - **Rationale:** Unreachable code is dead code. Redundant paths indicate a logic error or an opportunity for simplification. Reviewers flag this with comments like "i dont see any difference between the two branches, just remove the match" or "I think that's unreachable".
    - **Tooling:** TypeScript flags this via `allowUnreachableCode: false` (tsc) or Biome's `noUnreachable`. Python has no reliable ruff rule for general unreachable code (`B012` is `jump-statement-in-finally`, **not** an unreachable-code check) — rely on review + coverage. [1, 7]

6.  **Unnecessary React Hook Wrappers**
    - **Signature:** React `useCallback` or `useMemo` hooks wrapping already-stable values (like primitive constants or functions defined outside the component) or functions that are only passed to non-memoized components.
    - **Rationale:** These patterns add boilerplate and complexity without providing a performance benefit, making the code harder to read. Reviewers often state "remove useCallback 99% of the time its extra noise for very little value".
    - **Tooling:** AST-based checks for unnecessary React hooks. The `eslint-plugin-react-compiler` can help identify redundant memoization. [35, 41]

## Phase 2: Compile findings

After all agents report back, compile a single summary table with columns:

| File(s) | Lines | Hygiene Issue | Recommendation | Severity |
|---------|-------|---------------|----------------|----------|

Sort by severity (high first), then by file path.

Group the summary into:
- **High Severity** — Duplicated business logic; large, complex dead functions/classes; entire unused files.
- **Medium Severity** — Unused exported functions; large blocks of commented-out code; unnecessary wrappers; redundant code paths.
- **Low Severity** — Unused local variables or imports; minor unreachable code blocks.

## Phase 3: Generate fix plan

For each high or medium severity finding, output a concrete remediation plan:

- **For Duplicated Code:** "These code blocks are nearly identical. Extract this logic into a single, shared function in a suitable utility module and call it from all locations. This will reduce code size and prevent bugs from inconsistent updates."
- **For Unused Code:** "This function/class/variable `[name]` appears to be unused. Verify it is not being called dynamically, and if not, remove it. Tools like `vulture` (Python) or `knip` (TypeScript) can help confirm this. This is often flagged by rules like Ruff `F841` or `F401`."
- **For Commented-out Code:** "This block of code has been commented out, which adds clutter. Remove it. If the code is important, it can be retrieved from git history. This is flagged by Ruff rule `ERA001`."
- **For Unnecessary Wrappers:** "This `useCallback` hook wraps a function that does not appear to need memoization, adding unnecessary boilerplate. Remove the wrapper and pass the function directly."
- **For Unreachable Code:** "This code is unreachable because it follows a `return` or `throw` statement. Remove the dead code. In TypeScript this is flagged by the compiler (`allowUnreachableCode: false`) or Biome's `noUnreachable`; in Python there is no reliable ruff rule, so it is caught by review/coverage."
