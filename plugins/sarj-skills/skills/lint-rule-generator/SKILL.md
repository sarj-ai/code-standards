---
name: lint-rule-generator
description: Design and calibrate deterministic rules for demonstrated defects after checking existing controls.
---

Require reproduced failure, existing owner, enforcement gap, no-change harm,
valid boundary and smallest fix. Unsupported/source-freezing proposals need
explicit override. Prefer upstream controls or repairing their owner.
Apply [validation admission](../../commands/strengthen-ci-cd-and-tooling.md) to
preflight/readiness proposals too; a new helper's self-tests are not need evidence.

State `Routing: <repository>, because <evidence>`: Git-tree facts belong in
repo-standards; source/config semantics and integration in code-standards.
Parse semantic relationships; names cannot prove intent.

For saved findings, track the durable prevention outcome separately from any
application repair. Cite the owning rule, examples, severity and applicable group;
record publication and consumer state separately from calibration. Distinguish
full coverage from blind spots. When automation cannot distinguish
valid cases reliably, update the existing review command/skill with the reusable
decision and allowed boundary, explicitly marked judgment-only. A product-only fix does not satisfy a requested
standards change. Record unsupported or ambiguous proposals explicitly instead
of manufacturing a detector or claiming regression tests prevent other authors
from repeating the pattern.

Use `maintain rules new`/`prepare` for new rules; `verify` checks examples/tests
without changing severity. Keep metadata, registration, versions and artifacts
atomic. Run `make verify` with pinned native tools and a private non-Git temp root.

TypeScript rules are Oxlint `createOnce` plugin rules in
`packages/typescript/src/rules/<id>.ts`, with documentation and executable
examples in `src/docs/<id>.ts` and Oxlint RuleTester cases in
`tests/rules/<id>.test.ts`. Run `node scripts/oxlint/generate-index.ts` after
adding or removing one; `verify` runs the examples through Oxlint.

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
