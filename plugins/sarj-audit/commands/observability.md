Audit the codebase for observability hygiene, focusing on the three pillars: structured logs, metrics, and traces. High-quality observability is critical for production debuggability and reliability. This skill audits for common defects like unstructured log messages, missing correlation IDs, secret leakage, missing failure metrics, and incorrect log levels.

This skill does not cover silent error handlers (covered by `/sarj-audit:error-handling`) or the use of `print` in test files.

## What this audits

The audit covers common observability defects categorized into logs, metrics, and cross-cutting concerns.

### Pillar 1 — Structured Logs

- **`print()` and `console.log()` in application code**: These bypass structured logging, context, levels, and proper sinks. They are noise in production environments and should be replaced with a logger. (Ruff: `T201`, ESLint: `no-console`)
- **Unstructured f-string / template literal logging**: `logger.info(f"user {id} did {action}")`. These are impossible to query efficiently. The fix is to use key-value pairs: `logger.info("user_action", user_id=id, action=action)`. (Ruff: `G004`)
- **Missing stack traces on exception logs**: `except Exception as e: logger.error(f"Failed: {e}")` loses the stack trace. The fix is `logger.exception("Operation failed")`. **Library-specific:** stdlib `logging` also accepts `logger.error("...", exc_info=True)`, but **loguru** (the logger in use here) does **not** accept `exc_info=` — use `logger.exception(...)` or `logger.opt(exception=True).error(...)`. (Ruff: `TRY400` flags `logger.error` inside an `except` where `logger.exception` belongs. Note: `BLE001` is a *different* rule — blind `except Exception` — not a stack-trace check; do not cite it here.)
- **Incorrect log levels**: Using `logger.error` for non-fatal, expected conditions like user input errors or 4xx client responses creates alert fatigue. These should be `logger.warning` or `logger.info`.
- **Manual string prefixes instead of context binding**: Log messages with hardcoded prefixes like `logger.info("[MyService] Task started")` are not filterable. The fix is to use the logger's binding mechanism: `child_logger = logger.bind(service="MyService")`.

### Pillar 2 — Metrics

- **Missing metrics on critical failure paths**: `try/except` blocks that catch errors, or queue implementations that can drop items, must increment a failure/dropped counter. Without this, silent failures are invisible.

### Cross-cutting: Correlation & Secrets

- **Missing correlation ID binding**: Entry points must bind a `request_id` or `trace_id` to the logger context. Without this, it's impossible to trace a single request through the logs of multiple services.
- **Secret/PII leakage**: Logging variables named `token`, `api_key`, `password`, or full request/response bodies without redaction is a high-severity security risk. These must be redacted, hashed, or omitted from logs and traces.

## Phase 0: Discover project structure

Run the standard discovery pass first to identify source roots and languages. Then add the skill-specific items:

1.  **Identify logging libraries**: Detect `loguru` or `structlog` in Python, and `pino`, `winston`, or `console` usage in TypeScript/JavaScript.
2.  **Identify metrics/tracing libraries**: Detect `prometheus_client` or `opentelemetry-sdk` in Python, and `prom-client` or `@opentelemetry/api` in Node.js.
3.  **Identify request entry points**: Find FastAPI routers, Express handlers, Celery tasks, and other entry points where root spans and correlation IDs should be initialized.
4.  **Identify secret name patterns**: Augment a default list (`token`, `jwt`, `password`, `secret`, `api_key`) with project-specific secret variable names.

Output the discovered structure before proceeding.

## Phase 1: Audit (parallel agents)

Spawn parallel agents per source root. Each agent scans for the following corpus-derived violations.

### Category A — Logging Violations

1.  **`print()` or `console.log()` in application code**: Flag any use outside of CLI tools or designated debugging files (Ruff: `T201`, ESLint: `no-console`).
2.  **Unstructured f-string/template/concatenated logs**: Find calls to logger methods where the first argument is a `JoinedStr` (f-string), a `BinOp` (concatenation), or a template literal (Ruff: `G004`).
3.  **Missing stack traces**: Find `except` blocks that call `logger.error` / `logger.warning` without capturing the traceback (`logger.exception`, or stdlib `exc_info=True`) (Ruff: `TRY400`). For loguru codebases, the correct fix is `logger.exception(...)` — `exc_info=` is a stdlib-only kwarg.
4.  **Incorrect log levels**: Flag `logger.error` calls containing keywords indicative of client error (e.g., "not found", "invalid input", "permission denied", "blocked").
5.  **Hardcoded log prefixes**: Flag logger calls with regex `\[[A-Z_\-]+\]` in the message string, suggesting a move to `logger.bind()`.

### Category B — Metric & Trace Gaps

1.  **Missing failure metrics**: Flag `except` blocks or error-handling `if` statements that do not contain a call to a known metrics client (`.inc()`, `.observe()`).

### Category C — Secret & Correlation Gaps

1.  **Secret leakage**: Flag any logger or `set_attribute` call where a keyword argument matches a known secret name (`token`, `password`, etc.).
2.  **Missing correlation ID binding**: At identified entry points, verify that a correlation ID (`request_id`, `trace_id`, `call_id`) is bound to the logger context early in the request lifecycle.

### Severity assignment

-   **High**: Secret/PII leaks; missing stack traces on exception logs; missing failure metrics on critical paths.
-   **Medium**: Unstructured logs in hot paths; incorrect log levels causing alert fatigue; missing correlation ID binding.
-   **Low**: `print`/`console.log` in non-critical code; hardcoded log prefixes.

## Phase 2: Compile findings

After all agents report back, compile a single summary table:

| File | Line | Pillar | Category | Issue | Severity |
|------|------|--------|----------|-------|----------|

Sort by severity (high first), then by file path. Group the summary into High, Medium, and Low severity findings and print the total count.

## Phase 3: Generate fix plan

For each high-severity violation, output a concrete fix:

-   **For secret leaks**: Provide the redaction strategy (e.g., `logger.info("auth", token_prefix=token[:6])`).
-   **For missing stack traces**: Replace `logger.error(str(e))` with `logger.exception("operation_failed")`.
-   **For missing metrics**: Provide the `counter.inc()` or `histogram.observe()` snippet to add to the failure path.

For each medium-severity violation, output a one-line fix description:

-   **For unstructured logs**: `Rewrite logger.info(f"...") to use structured key-value pairs.`
-   **For incorrect log levels**: `Change logger.error(...) to logger.warning(...) for user-facing errors.`
-   **For missing correlation**: `Add logger.bind(request_id=...) at the start of the request handler.`

Do NOT automatically rewrite code. Present the plan for review and include the warning: "Before applying, audit the downstream consumers (dashboards, alerts, log-based metrics) that depend on the current format."
