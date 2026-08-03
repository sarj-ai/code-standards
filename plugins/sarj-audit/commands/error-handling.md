# Error handling

Audit exception and failure handling using the shared [audit protocol](../README.md#audit-protocol).

## Automated baseline

Run applicable Ruff `E722`, `BLE001`, `S110`, `S112`, and `TRY400`, ESLint promise/catch checks, and Sarj `no-sentinel-return-on-except`, `no-sentinel-return-on-catch`, `no-fat-try-blocks`, `no-log-only-catch`, and `no-silent-promise-catch`.

## Judgment checks

- Broad catches below a true process, request, worker, or SDK boundary.
- Expected failures converted to ambiguous sentinels or unrelated exception types.
- Partial state left behind after a failure, missing cleanup, or retries that duplicate side effects.
- Error responses that leak internals or erase actionable domain context.

Do not demand local logging when a higher boundary records the error once with context. Avoid duplicate logging and catch/rethrow wrappers that add no information.
