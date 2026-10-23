---
name: audit-protocol
description: Run a requested domain audit using Sarj's shared command sources and verified findings.
---

Audits are read-only unless implementation is requested. Load the selected
`../../commands/` file relative to this skill; Claude: `/sarj-skills:<command>`.

Identify owning repositories, stack and boundaries; search named source paths
with bounded output. Exclude unrelated task outputs, caches, duplicate worktrees
and generated/vendor/fixture data. Run native checks before judging
uncovered behavior; inspect framework guards.
Require completed exit statuses; interrupted checks are inconclusive.
Keep reports ignored and private; redact secrets/identifiers.

Report severity, location, evidence, impact, smallest fix, confidence and owning
tool/rule or `judgment-only`; report clean scopes too.

For interruption, save objective, worktree, base/head/tree, commands/statuses,
reports/PRs, owned processes and next action. Reconcile revisions before reuse;
reference private history instead of copying it.
