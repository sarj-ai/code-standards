# CI/CD and tooling

Apply [protocol](../skills/audit-protocol/SKILL.md).

Before adding preflight/readiness commands, reports or shadow configuration
schemas, name the current operational decision they change and the failure
existing checks miss. Extend the enforcing owner first. Package ownership,
passing self-tests or lists of unknowns do not establish need. Retire redundant
helpers and tests that cover only them; preserve deployment, startup, admission
and CI contracts.
Apply this to application tooling and IaC.

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

Keep IaC changes to the requested configuration and required delivery wiring.
Use one-off disposable checks for change verification; keep rehearsal helpers
and reports outside Git and summarize commands/results in the PR.
Do not turn task verification into a new script, dependency, Make target or CI job.
A permanent check needs a named recurring regression existing gates miss, an owned
harness, a bounded runtime and an actionable failure. Reuse that harness; scope
execution to affected inputs, including shared dependencies and security boundaries.

Keep plans, state, logs, inventories and execution narratives out of the diff.
Follow repository documentation policy; when a durable operator-contract update
is allowed and required, make the smallest edit at its existing source. Do not
append rollout diaries, verification transcripts or duplicated configuration.
