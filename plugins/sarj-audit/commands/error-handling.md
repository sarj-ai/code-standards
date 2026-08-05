# Error handling

Audit exception and failure handling using the shared [audit protocol](../README.md#audit-protocol).

## Judgment checks

- Broad catches below a true process, request, worker, or SDK boundary.
- Expected failures converted to ambiguous sentinels or unrelated exception types.
- Partial state left behind after a failure, missing cleanup, or retries that duplicate side effects.
- Error responses that leak internals or erase actionable domain context.

Do not demand local logging when a higher boundary records the error once with context. Avoid duplicate logging and catch/rethrow wrappers that add no information.
