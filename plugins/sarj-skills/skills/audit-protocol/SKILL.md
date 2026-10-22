---
name: audit-protocol
description: Run a requested domain audit using Sarj's shared command sources and verified findings.
---

# Audit protocol

Audits are read-only unless implementation is requested. Read only the selected
file under `../../commands/`, relative to this skill's real directory; Claude
exposes it as `/sarj-skills:<command>`.

Identify the stack, authored boundaries and native checks. Run deterministic
checks first and report verified findings once. Domain commands cover remaining
judgments; exclude irrelevant generated/vendor/fixture data. Trace framework
guards before claiming a local omission.

Require completed checks and actual exit statuses; missing reports, interruption
and unavailable prerequisites are incomplete evidence. Keep JSON reports in an
ignored, owner-readable directory inside the checked repository.

Report by severity: location, evidence, impact, smallest fix, confidence and owning
rule/tool or `judgment-only`. Omit speculation. If clean, name examined checks/scopes.

For interrupted work, keep one private handoff with objective, worktree,
base/head/tree, commands/statuses, reports, PRs, owned processes and next action.
On resume, reconcile revisions before reusing evidence; reference private history
rather than copying transcripts.
