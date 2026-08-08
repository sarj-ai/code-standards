# Observability

Audit production logs, metrics, and traces using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol). Silent catches belong in `error-handling`.

## Judgment checks

- Unstructured application logs, missing exception context, or fields embedded only in prose.
- Missing request/trace/job identifiers across asynchronous or distributed boundaries.
- Critical failure, retry, queue-drop, saturation, or latency paths without useful metrics/traces.
- Levels that create alert fatigue or hide operational failures.
- Secrets, credentials, sensitive payloads, or unnecessary PII in telemetry.

Respect the configured logging library: APIs differ. Do not demand telemetry for every function; focus on boundaries and operationally actionable events, and avoid recording the same error at multiple layers.
