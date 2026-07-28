Audit the codebase for improper exception handling patterns. The goal is to ensure that errors are handled in a way that makes the system robust, debuggable, and observable. Errors should be specific, and unexpected exceptions should be allowed to fail loudly.

## What this audits

This audit flags common anti-patterns that mask bugs and complicate debugging. It prioritizes catching specific, expected exceptions at the appropriate level of abstraction while letting unexpected errors propagate to a global handler for logging and alerting.

## Phase 0: Discover project structure

Run the standard discovery pass first to enumerate source roots and languages. Then, add the following skill-specific items:

- Identify top-level request handlers (e.g., FastAPI routers, Next.js API routes), background job entry points, and SDK/library boundaries. These are often the correct locations for broad, top-level exception handling and logging, whereas deeper application code should be more specific.

Output the discovered structure before proceeding.

## Phase 1: Audit (parallel agents)

Spawn agents to search their assigned scopes for the following violations. Each agent should report the file, line range, violation type, and severity.

### Python Agents

- **PY-1: Bare or Overly Broad `except` (High Severity):** Scan for `except:`, `except Exception:`, and `except BaseException:`. These are high-severity violations unless they are at the outermost layer of a request handler or background job, and they log the full exception with a stack trace (`exc_info=True`) before returning a standard error response. (ruff: `E722`, `BLE001`). [9, 18, 19]
- **PY-2: Swallowed Exceptions (High Severity):** Scan for `except ...: pass`, `except ...: continue`, or `except` blocks that log a message without the exception context (i.e., missing `exc_info=True` or `logger.opt(exception=True)`). This makes debugging impossible. (ruff: `S110`, `S112`). [1]
- **PY-3: Returning Sentinel Values on Error (Medium Severity):** Scan for `try...except` blocks where the `except` block returns `None`, `False`, or an empty list (`[]`). This pattern hides the original error from the caller and conflates "not found" with "an error occurred".
- **PY-4: Conflating Distinct Errors (High Severity):** Scan for `except` blocks (e.g., `except UniqueViolation`) that handle multiple distinct database constraints or error types with a single, generic error message, which can mislead the user or caller.
- **PY-5: Overly Large `try` Blocks (Medium Severity):** Scan for `try` blocks that span more than 5-7 lines or contain multiple independent I/O operations. The error handling becomes ambiguous.
- **PY-6: Unnecessary `try...except` (Low Severity):** Scan for `try...except` blocks that immediately `raise` the caught exception without adding context or logging. This adds noise and can be removed.

### TypeScript/JavaScript Agents

- **TS-1: Empty or Log-Only `catch` Blocks (High Severity):** Scan for empty catch blocks (`catch (e) {}` or `catch {}`) or blocks that only call `console.log`/`console.error` without re-throwing the error, especially in library or data-access code. (typescript-eslint: `no-empty-function`). [2, 31]
- **TS-2: Returning Sentinel Values on Error (Medium Severity):** Scan for `catch` blocks that return `null`, `false`, or an empty array (`[]`) instead of throwing an application-specific error.
- **TS-3: Unnecessary `catch` Blocks (Low Severity):** Scan for `catch (e) { throw e; }`. This is redundant and can be removed to let the error propagate naturally. (eslint: `no-useless-catch`). [13, 17, 21]
- **TS-4: Overly Large `try` Blocks (Medium Severity):** Scan for `try` blocks that wrap entire function bodies or multiple independent `await` calls, making it unclear which operation failed.

## Phase 2: Compile findings

After all agents report back, compile a single summary table with columns:

| File | Lines | Violation | Recommendation | Severity |
|------|-------|-----------|----------------|----------|

Sort by severity (high first), then by file path. Group the summary into High, Medium, and Low severity findings.

## Phase 3: Generate fix plan

For each high-severity finding, output a concrete remediation plan:

- **For Broad/Bare/Empty Catches:** "Replace the broad/bare/empty `except` clause with one or more specific exception types that are expected and can be handled (e.g., `except FileNotFoundError:`, `except httpx.RequestError:`). Let all other unexpected exceptions propagate to a global error handler." [11, 19]
- **For Swallowed Exceptions:** "In the `except` block, either re-raise the exception (`raise`), raise a new domain-specific exception (`raise UserNotFoundError from e`), or log the full stack trace with `logger.opt(exception=True).error(...)` before returning a generic error response." [1]
- **For Returning Sentinel Values:** "Instead of catching the exception and returning `None` or `False`, either let the original exception propagate, or catch the specific exception and raise a new, more specific application-level exception (e.g., `raise UserNotFoundError(user_id) from e`). This makes failures explicit for callers." [20]
- **For Large `try` Blocks:** "Reduce the scope of the `try` block to wrap only the specific operation that is expected to fail (e.g., the single network call, database query, or file I/O operation). Move variable initializations and other non-failing logic outside the block." [24]
- **For Conflating Errors:** "Inside the `except` block, inspect the exception object to differentiate between root causes. For example, check the database constraint name (`except UniqueViolation as e: if e.diag.constraint_name == '...':`) and return a distinct, specific error for each case."

Do NOT automatically implement fixes. Present the plan for review and wait for confirmation before making changes.
