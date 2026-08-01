# `_logging` — evidence

Shared helper. This file holds what the code cannot: the measurements behind
each threshold, the false-positive families the guards exist to stop, and the
alternatives that were rejected.

Shared helpers for recognising logging / error-reporting calls.
Used by `no-log-only-catch`, `no-sentinel-return-on-catch` and
`no-secret-in-log` so all three rules agree on what counts as "this call
writes to a log sink" before deciding a catch silently swallows an error or a
secret leaks.

Two shapes are recognised:

  - **Receiver-shaped** — a log METHOD (`debug`/`info`/`warn`/`error`/…) on a
    logger RECEIVER: `console.error(...)`, `logger.warn(...)`,
    `this.logger.info(...)`, and builder/factory chains
    (`logger.bind({...}).info(...)`, `logging.getLogger(n).info(...)`).
  - **Free-function-shaped** — a project-declared logging function, e.g.
    `logEvent("pr_scan.failed", { repo, error })`. Structured loggers that are
    plain functions taking a meta object are the dominant real-world shape and
    have no logger receiver at all, so they are invisible to the receiver
    heuristic. Projects declare theirs via the shared `logFunctions` rule
    option; `loggerNames` extends the receiver set the same way.

Both options are OFF by default (empty), so default behaviour is unchanged.
Declaring them makes the catch rules stop reporting a correctly-logged
degraded return AND makes `no-secret-in-log` start inspecting those calls —
the second effect closes a real hole, since `logEvent("auth", { botToken })`
was previously never examined.
