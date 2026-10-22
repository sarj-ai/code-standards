---
name: lint-rule-generator
description: Design and calibrate deterministic rules for demonstrated defects after checking existing controls.
---

# Lint rule generator

Require a reproduced failure, existing owner, gap, no-change harm, valid boundary
and smallest fix. Unsupported or source-freezing proposals need explicit override.

State `Routing: <repository>, because <evidence>`. Git-tree facts belong in
repo-standards; source/config semantics and tool integration in code-standards.
Prefer upstream controls or repairing the existing owner. Use parsers for semantic
relationships; names alone cannot establish intent.

From source, use `maintain rules new`/`prepare` for new rules; `verify` checks
examples and focused tests without changing severity. Keep registration,
metadata, versions and derived artifacts atomic.

Use [evaluation](references/evaluation-protocol.md) for labeled cases, corpus
judgment, diagnostic interactions and fix convergence. Run `make verify` with CI's
pinned native preparation in one shell and a private non-Git fixture temp root.

Promotion needs a separate metadata change after a warning release, except
unambiguous security/correctness defects. Publish before consumer rollout.
