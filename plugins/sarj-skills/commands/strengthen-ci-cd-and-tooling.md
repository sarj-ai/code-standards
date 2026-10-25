# CI/CD and tooling

Apply [protocol](../skills/audit-protocol/SKILL.md).

Trace required gates through delivery, deployment order, health/rollback and
configuration drift. Optimize demonstrated bottlenecks using pinned
baseline/candidate revisions and equivalent inputs, harness, caches and
concurrency. Separate queue/execution time; measure readiness, useful errors,
repeated work or output cost. Preserve final qualification gates; modernization
needs observable benefit.

Before polling PR checks, confirm mergeability and that expected workflows
started for the current head. Merge conflicts can suppress `pull_request`
workflows while other checks pass; resolve that cause before waiting or
claiming qualification. Poll pending runs with backoff; reuse immutable diffs
and commit metadata, and retrieve relevant logs only for failed jobs.
After a new commit, reconcile the head and expected workflows again.

Trace stack inputs and matrices to command targets. Generalize shared contracts
across supported stacks while retaining authorization and capability boundaries;
reuse the declared stack set. A stack comparison alone does not prove a defect.
Use native lint, type, build and smoke checks first. Add operational unit tests
only for a distinct missed wrong outcome; follow [test judgment](../skills/test-value/references/oracles.md).
