---
name: lint-rule-generator
description: Design, route, and calibrate deterministic rules from demonstrated defects, including upstream overlap, false positives, and warning-first adoption.
---

# Lint rule generator

Use [authoring-workflow.md](references/authoring-workflow.md) for scaffolding and
lifecycle details.

1. Record the concrete defect, existing owner, demonstrated gap, no-change harm,
   valid-state boundary, and smallest fix. Unsupported or source-freezing
   proposals return `delete/no PR`; implementation needs an explicit override.
2. State `Routing: <repository>, because <evidence>`. Git-tree facts belong in
   repo-standards; source/config semantics and tool integration belong here.
3. Search upstream and Sarj catalogs before adding code. Prefer maintained
   upstream rules and syntax-aware analysis. Do not infer intent from names.
4. Write labeled positives, negatives, near misses, and interaction cases.
   Reuse fixtures and adequate regression coverage; no per-comment test quota.
5. Register implementation, metadata, versions, docs, and tests atomically.
   Stage warnings and synchronize artifacts through the existing CLI.
6. Verify focused behavior, self-lint, pinned local corpora, diagnostic
   precedence, fix convergence, and performance. Run `make verify` before review.
7. Report evidence, counts, limitations, commands, and release recommendation.

Use [language-routing.md](references/language-routing.md) to select an engine and
[evaluation-protocol.md](references/evaluation-protocol.md) for corpus work.
Warning promotion requires a separate metadata change after a warning release,
except unambiguous security/correctness defects. Broad test-oracle advisories
remain review candidates; they never authorize deletion.

Keep private corpora owner-readable and public reports redacted. Cloning,
installation, publishing, external mutation, and consumer rollout require
session authorization. Publish before the rollout controller updates consumers.
