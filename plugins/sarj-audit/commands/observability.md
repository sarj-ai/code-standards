# Observability

Audit production logs, metrics, and traces using the shared [audit protocol](../README.md#audit-protocol). Silent catches belong in `error-handling`.

## Automated baseline

Run applicable Ruff `T201`, `G004`, and `TRY400`, ESLint `no-console`, and Sarj `no-fstring-in-log`, `no-stdlib-logging`, and `no-secret-in-log`.

## Judgment checks

- Unstructured application logs, missing exception context, or fields embedded only in prose.
- Missing request/trace/job identifiers across asynchronous or distributed boundaries.
- Critical failure, retry, queue-drop, saturation, or latency paths without useful metrics/traces.
- Levels that create alert fatigue or hide operational failures.
- Secrets, credentials, sensitive payloads, or unnecessary PII in telemetry.

Respect the configured logging library: APIs differ. Do not demand telemetry for every function; focus on boundaries and operationally actionable events, and avoid recording the same error at multiple layers.
