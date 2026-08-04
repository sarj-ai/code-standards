# Standards as the single authority + audit every rule pair for contradictions

Status: **CONFIG AUTHORITY IMPLEMENTED; exhaustive pair audit remains open.**
Date: 2026-08-03.
Triggered by a live incident: a teammate was blocked in consumer A by two rules
that cannot both be satisfied.

## The incident (fixed and permanently guarded, read this first)

`DOC201` / `DOC402` fire when a `Returns:` / `Yields:` section is **absent**.
`SARJ092 no-typed-doc-sections`, new in standards 0.42, deletes exactly those
sections. Both are errors. **No valid docstring exists** for any typed function:
write the section → SARJ092 fires; omit it → DOC201 fires. Neither is
author-silenceable.

- A merged downstream hotfix ignores DOC201/DOC402.
- A follow-up corrects an over-broad part of that hotfix: it had also disabled
  `D417`, which is **not** a conflict. `D417` fires only on a *partial* `Args:`
  section, so deleting the section satisfies D417 and SARJ092 at once. Disabling
  it silently dropped a real check on docstrings that lie about the signature.
- `DOC501` stays enabled: SARJ092 does not govern `Raises:`.
- Standards 0.43 rejects child Ruff configs that replace inherited `select` or
  `ignore`, and a permanent invariant keeps `DOC201` / `DOC402` ignored while
  the typed-docstring policy forbids those sections.

Verified empirically, not by reading config: only consumer A was affected.
Consumers B and D pass probe files; consumer C has no Python lint config.

## Why it happened — the mechanism, not the rule

Ruff's `ignore` in a child config **replaces** the inherited list; it does not
extend it. Consumer A re-enables 22 canonical-ignored rules to run *stricter* than
the standard, and the only way to express that with `ignore` is to restate every
other ignore by hand. That hand-copied list is a frozen snapshot of a moving
target: when 0.42 shipped SARJ092, canonical's list accounted for it and the
consumer's copy could not. Nothing detected the divergence.

`extend-ignore` appends instead of replacing. The consumer's `extend-select` already
works this way, which is why its strictness *additions* survive cleanly.

### Measured divergence (consumer A vs canonical)

- canonical ignores: 43 · consumer A local ignores: 33
- Consumer A **re-enables 22** canonical-ignored rules: `D200 D205 D400 D401 D403
  D404 D405 D406 D407 D408 D409 D410 D411 D412 D413 D415 D416 D417 D420 D421
  DOC501 PLC2701` — all docstring ceremony except `PLC2701` (which canonical
  ignores deliberately because SARJ048 supersedes it).
- Consumer A is **looser on 12**: `A002 A003 INP001 PLR0904 PLR0914 PLR0917 PLR1702
  RUF105 RUF201 S101 S105 S106`. Canonical handles `S101/S105/S106` correctly
  via test-scoped `per-file-ignores` — strictly better than the consumer's repo-wide
  silencing — and enforces `PLR0904/0914/0917/1702`.

**So canonical is already the stricter authority on real code rules. Consumer A is
stricter only on docstring prose ceremony, which is explicitly unwanted.**

### Resolved implementation detail

The child `[tool.ruff.lint]` table declares `select`, which causes Ruff to lose
the parent table's `ignore` values. Replacing the child `ignore` with
`extend-ignore` restores the canonical policy; it then exposes only stale
`noqa` directives for rules canonical no longer enables. Remove those
directives incrementally rather than reinstating docstring-demanding rules.

## The work

### 1. Make standards the only authority

Implemented: consumers inherit canonical policy and may only add strictness,
never silently diverge.

- Convert consumer `ignore` lists to `extend-ignore`, then remove obsolete
  `noqa` directives by affected source area.
- Canonical absorbs any strictness worth keeping — **but not the docstring
  ceremony family** (`D2xx`/`D4xx`, `DOC501`). House policy is: no docstrings,
  no comments. Rules that DEMAND prose must stay ignored canonically and must
  never be re-enabled downstream.
- Leave `PLC2701` ignored (SARJ048 supersedes it).

### 2. Gate it in `doctor`, not `scripts/` — implemented

`sarj_lint_configs/doctor.py` already runs in the consumer root and has
DRIFT/WARN levels; today it only checks version drift (pins, pre-commit revs,
eslint-plugin, retired rules). It does not check **policy** drift.

`doctor` now emits DRIFT when Ruff policy is split across multiple config files
or an extending config declares replacement `select` or `ignore` policy. It
directs consumers to one authority with additive `extend-select` /
`extend-ignore`, preserving canonical exclusions such as `DOC201` / `DOC402`.
`scripts/` cannot provide this protection — it only sees the standards tree,
while the gate must run where the failure travels.

Regression tests reproduce the broken consumer shape, prove split authority and
both replacement keys fail, prove one additive config passes, and pin the
contradictory docstring pair in the canonical ignore set.

### 3. Audit ALL rules for contradictory pairs

This incident was found by a blocked teammate, not by us. Assume more pairs
exist. Audit every active rule against every other, across ecosystems.

Scope: 151 live rules (77 Python, 56 TypeScript, 12 SQL, 3 IaC, 3 text/config)
**plus** every Ruff/ESLint rule the canonical configs enable — the DOC201 case
was a Sarj-rule-vs-Ruff-rule conflict, so a Sarj-only audit would have missed it.

A contradiction is: two enabled rules where **no source text satisfies both**.
Distinguish carefully from a *tension* that a third form resolves —
`D417` vs SARJ092 looks like a conflict but deleting the section satisfies both.

Method:
- Classify each rule as DEMANDS-X or FORBIDS-X over the same construct
  (docstring sections, comments, imports, ordering, formatting).
- Pay special attention to rules that fire on **absence** — those are the ones
  that cannot be satisfied by deletion.
- For each suspected pair, write a probe file and prove unsatisfiability by
  running both linters. Empirical only; config greps produced two false
  positives in this investigation.
- Highest-risk families given house policy: the new 0.42 comment rules
  (SARJ090 prefer-single-sentence-comment, SARJ091 no-long-comment,
  SARJ092 no-typed-doc-sections) against every pydocstyle `D*`, pydoclint
  `DOC*`, and any ESLint jsdoc/comment rule.
- Land the audit as a permanent test, not a one-off report, so a new rule cannot
  reintroduce a contradiction.
