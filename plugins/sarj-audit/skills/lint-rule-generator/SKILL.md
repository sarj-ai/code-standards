---
name: lint-rule-generator
description: Designs, evaluates, and refines deterministic lint rules from concrete anti-patterns. Use when creating a Python, TypeScript, Markdown, SQL, IaC, or config rule; checking whether an upstream rule already covers a problem; calibrating false positives on local corpora; or deciding whether a new rule is safe to introduce as a warning or error.
---

# Lint rule generator

Turn a concrete defect description into the narrowest deterministic rule that
earns trust on real code. Use `sarj_lint_configs.libs.rules` for problem,
catalog, evaluation, and report contracts. Use `sarj_lint_configs.libs.corpus`
for manifests, snapshots, local pin verification, and redacted reporting. Keep
all executable logic in the uv package; this skill contains no scripts.

Read [language-routing.md](references/language-routing.md) before choosing an
engine. Read [evaluation-protocol.md](references/evaluation-protocol.md) before
running or reporting a corpus evaluation.

## Required workflow

1. Restate the request as one `RuleProblem`: observable bad pattern, concrete
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
   new judgment-heavy rule at warning severity.
6. Run focused tests, Ruff/ESLint, type checking, package tests, and the
   repository's own `sarj-standards check`. Fix contradictions and diagnostic
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
