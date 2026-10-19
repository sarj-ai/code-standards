# Error handling

Audit exception and failure handling using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).

## Judgment checks

- Broad catches below a true process, request, worker, or SDK boundary.
- Expected failures converted to ambiguous sentinels or unrelated exception types.
- Partial state left behind after a failure, missing cleanup, or retries that duplicate side effects.
- Error responses that leak internals or erase actionable domain context.
- Shell failure handlers that need the original exit status but capture the
  negated status from `if ! command` or overwrite `$?` through intervening commands.
  Capture the original status immediately in the failure arm of `if command`;
  boolean-only negation and intentional recovery remain valid.

Do not demand local logging when a higher boundary records the error once with context. Avoid duplicate logging and catch/rethrow wrappers that add no information.

The upstream `preserve-caught-error` warning also checks error wrappers in
parameterless catches. When adding context with `throw new Error(message)`,
retain the original exception as `{ cause }`. Ordinary recovery catches and
errors created inside a separate nested function keep their own contracts.
