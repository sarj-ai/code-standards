# Error handling

Apply [protocol](../skills/audit-protocol/SKILL.md).

Trace recovery and partial state at actual failure boundaries. Retain domain
context and request/job identity across async boundaries; log actionable failures
once, with useful levels and privacy-safe context. Catch/rethrow wrappers need
added information.

Capture shell failure status immediately in `if command`'s failure arm;
`if ! command` exposes the negated status.
