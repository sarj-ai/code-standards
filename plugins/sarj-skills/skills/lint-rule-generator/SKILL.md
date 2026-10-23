---
name: lint-rule-generator
description: Design and calibrate deterministic rules for demonstrated defects after checking existing controls.
---

Require reproduced failure, existing owner, enforcement gap, no-change harm,
valid boundary and smallest fix. Unsupported/source-freezing proposals need
explicit override. Prefer upstream controls or repairing their owner.

State `Routing: <repository>, because <evidence>`: Git-tree facts belong in
repo-standards; source/config semantics and integration in code-standards.
Parse semantic relationships; names cannot prove intent.

Use `maintain rules new`/`prepare` for new rules; `verify` checks examples/tests
without changing severity. Keep metadata, registration, versions and artifacts
atomic. Run `make verify` with pinned native tools and a private non-Git temp root.

Evaluate immutable corpora without silent repinning: labeled bad/near-miss cases,
live hits or disclosed unbiased samples, TP/FP/FN/TN, duplicates and blind spots.
Use `run_isolated_corpora`; check affected suppressions/severity/precedence/malformed
input and semantic fix/formatter convergence. Compare repeated cold/warm medians
and available peak memory against baseline under equivalent inputs/environment.

Recommend reject, revise, warning or error with commands/limitations. Error advice
requires no known inspected false positives; promotion normally needs a separate
change after a warning release, except unambiguous security/correctness defects.
Publish before rollout; public reports expose redacted aggregates, not private
source, paths or identifying hashes.
