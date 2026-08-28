---
name: lint-rule-generator
description: Routes, designs, evaluates, and refines deterministic rules from concrete anti-patterns. Use when creating repository policy or a Python, TypeScript, Markdown, SQL, IaC, or config rule; checking whether an upstream rule already covers a problem; calibrating false positives on local corpora; or deciding whether a new rule is safe to introduce as a warning or error.
---

# Lint rule generator

Turn a concrete defect description into the narrowest deterministic rule that
earns trust on real code. Use `sarj_standards.libs.rules` for problem,
catalog, evaluation, and report contracts. Use `sarj_standards.libs.corpus`
for manifests, snapshots, local pin verification, and redacted reporting. Keep
all executable logic in the uv package; this skill contains no scripts.

## Admit the proposal before routing

Before routing or editing any proposed CI guard, preflight, validator, policy
workflow, or new or expanded lint rule, record all of the following internally:

1. the concrete failure mode, evidenced by a local incident, a reproducible
   upstream incident, an authoritative security or correctness advisory, or a
   minimal reproduction rather than an unsupported hypothetical;
2. the exact existing owner or control for the invariant;
3. the demonstrated gap in that owner or control;
4. the concrete harm if no change is made;
5. whether the proposal distinguishes invalid state from merely changing
   today's valid configuration; and
6. the smallest fix at the owning boundary.

If evidence for the failure mode, demonstrated gap, or no-change harm is absent,
or the proposal only freezes today's source spelling, configuration value, or
temporary state, stop with `delete/no PR` and ask for an explicit user override.
Deleting a redundant check is a valid remediation. Moving the same weak oracle
into a script, changing it to inspect plan JSON without proving the missing
invariant, or otherwise hiding it from a detector is not a fix; rerun this
admission gate whenever the proposal is rewritten.

## Route before editing

State `Routing: <repository>, because <required evidence>` before touching rule source.

- Use `sarj-ai/repo-standards` when the finding requires an exact tracked Git tree: file
  existence, basename or placement, repository topology or migrations, pull-request size,
  ownership, delivery/GitHub state, or a repository-wide API/document set.
- Use `sarj-ai/code-standards` when the finding requires source or configuration semantics in
  Python, TypeScript, SQL, Terraform/HCL, Markdown, YAML, JSON, or shell, or changes lint
  engines, presets, baselines, adoption, release, or fleet rollout.
- Paths may select a semantic parser. If the path alone is sufficient to emit the finding,
  the rule belongs in `repo-standards`. Never add an organization- or repository-specific
  filename to a language rule merely because the file has that language's suffix.

For example, banning a tracked Terraform verifier filename belongs in `repo-standards`;
rejecting an environment-derived Terraform access expression belongs in `code-standards`.

Read [language-routing.md](references/language-routing.md) before choosing an
engine. Read [evaluation-protocol.md](references/evaluation-protocol.md) before
running or reporting a corpus evaluation.

## Required workflow

1. After routing, restate the request as one `RuleProblem`: observable bad pattern, concrete
   harm, evidenced languages, explicit non-goals, exclusions, bad examples,
   good examples, and strongest defensible fix policy. Ask for clarification
   only when two interpretations would produce materially different findings.
2. Search the owning upstream linter and the Sarj catalog. Record candidates,
   why configuration cannot express the request, and any overlapping rule IDs.
   Prefer augmenting a maintained upstream rule or preset.
3. Select syntax-aware analysis whenever comments, strings, scopes, aliases, or
   nesting can make regex ambiguous. Never infer intent from names alone.
4. Write labeled `EvaluationCase` values before implementation. Cover exact
   positives, minimal negatives, near misses, nested forms, aliases, generated
   code, fixtures, suppressions, malformed input, duplicate diagnostics, and
   multi-rule precedence. For fixes, include semantic preservation and a second
   pass that must produce no change.
5. Implement the smallest rule and register it atomically with its metadata,
   strict config, ledger entry, tests, docs, and owning package version. Keep a
   new judgment-heavy rule at warning severity. From the Standards repository,
   stage its lifecycle and synchronize all derived rule artifacts with:
   `code-standards --root . maintain rules stage-warning ENGINE:RULE-ID`.
6. Run focused tests, Ruff/ESLint, type checking, package tests, and the
   repository's own `code-standards check`. Fix contradictions and diagnostic
   thrashing rather than adding broad suppressions.
7. Evaluate against pinned, already-local corpora under the protocol. Inspect
   every match when feasible; otherwise use a deterministic unbiased sample and
   state its seed/selection rule. Classify every inspected hit.
8. Measure cold and warm wall time, files/bytes scanned, peak memory when
   available, and rule-only overhead. Compare against the runner without the
   candidate rule; do not call an optimization successful without a baseline.
9. Refine until there are no known false positives in the inspected corpus,
   no duplicate locations, no unstable fixes, and no unexplained regression.
   Preserve documented false negatives when avoiding them requires guesses.
10. Produce a reproducible report: rule ID, severity, implementation location,
    test commands, corpus pins or redacted labels, TP/FP/FN counts, sampling,
    interactions, timings, limitations, and promotion recommendation.

Before opening the PR, run
`code-standards --root . maintain rules changes --before origin/main --after HEAD`
and `make verify`. Do not manually clone or modify consumer repositories during
rule authoring; downstream propagation starts only after publication through
the rollout controller.
When the task also includes publishing or propagating the resulting Standards
bundle, hand off to `rollout-standards-release` after publication. Do not claim
the release or propagation complete until that skill's fleet status gate passes.

## Promotion gate

Default to warning. Recommend error only when all labeled cases pass, evaluated
corpora have zero known false positives, duplicate precedence is deterministic,
fixes are idempotent, self-lint passes, and performance is within the documented
budget. Promotion is a separate metadata change after at least one warning
release unless the rule detects an unambiguous security or correctness defect.

## Safety and privacy

Never download, clone, fetch, install, mutate external repositories, commit, or
publish unless separately authorized. Public manifests may contain public repo
identity and full immutable commit pins. Private corpora belong only in an
explicit `chmod 600` overlay. Never copy their names, absolute paths, source,
snippets, or hashes that reveal identity into public fixtures, diffs, logs, or
reports; use `CorpusSource.report_name`.
