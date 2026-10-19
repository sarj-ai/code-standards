---
name: audit-protocol
description: Run a requested Sarj judgment-layer domain audit from the shared command sources, with read-only discovery and evidence-backed reporting.
---

# Audit protocol

Every audit command follows this read-only workflow unless the user separately requests implementation. Domain commands contain only judgment checks. Deterministic checks are centralized in `code-standards`; do not duplicate their findings in an audit report.

For a named domain audit in a source checkout, read its existing file under
`../../commands/`, resolved from this skill's real directory. Load only the
selected command. Claude plugin installations expose these same bodies as
`/sarj-audit:<command-name>`.

## Discover

- Inspect manifests, lockfiles, source roots, generated boundaries, framework configuration, database dialect, and native lint, type, and test commands.
- Run deterministic checks first and verify their findings in source.
- Gate checks by the detected stack, including database, runtime, rendering, and tenancy differences.
- Prefer the repository's existing affected-check plan during iteration; preserve
  its full-check fallback and final qualification requirements.

For large checks, use an ignored, owner-readable task-local directory inside the
repository. `code-standards check --format json --output PATH` requires output
inside that root and writes it atomically; inspect its rule, location, help, notes,
and fix metadata. Record the command's actual exit status before summarizing
the first actionable diagnostic and report path. A missing report, interrupted
command, or failed pipeline is incomplete evidence, even if its last lines look
clean. Native interactive hook output can keep streaming.

## Review

Inspect only the selected command's concerns across applicable source roots. Exclude vendored, generated, fixture, snapshot, build, and lock files unless the command explicitly targets them.

## Report

Order findings by severity and confidence. Each finding includes its file and line, evidence and impact, the smallest credible remediation, confidence, and its supporting deterministic rule or tool, or `judgment-only`.

Separate confirmed defects from suggestions. Omit speculative, stylistic, duplicate, and unverified tool findings. When no findings remain, state the scopes and checks examined.

When pausing a long audit, update one bounded task-local JSON handoff alongside its
reports: objective, worktree, base/head/tree, check commands and exit statuses,
report paths, existing PRs, owned running processes, blocker, and next action.
Use the existing harness/activity resume mechanism. On resume, compare the
recorded revisions and worktree changes before reusing check evidence; rerun
checks affected by a changed tree or comparison base. Keep pointers to private
history instead of copying transcripts into the handoff or source tree.
