# Error handling

Use the [audit protocol](../skills/audit-protocol/SKILL.md).

Review catches below true failure boundaries, erased domain context, ambiguous
recovery and failures leaving partial state. Log once at the owning boundary;
catch/rethrow wrappers need added information. Native rules own silent catches,
leaked exceptions and cause preservation.

When shell recovery needs an exit code, capture it immediately in the failure
arm of `if command`; `if ! command` exposes the negated status. Preserve deliberate
boolean negation and recovery behavior.
