# `@sarj/ban-loose-type-guards-in-tests` — retirement record

> **RETIRED.** Deleted in #183 (`7316369`), in `@sarj/eslint-plugin` 5.0.0.
> This rule never had an evidence document, so there is nothing to archive; this
> file exists because the justification on record is not supportable and the
> record is the only thing left.

## The deletion was right

Verified against the blob at `7316369^`
(`git show 7316369^:packages/typescript/src/rules/ban-loose-type-guards-in-tests.ts`):

- **No test module.** `packages/typescript/tests/rules/` contained no
  `ban-loose-type-guards-in-tests.test.ts` at any commit. Nothing pinned its
  behaviour, which is why `check-file-conventions.sh` §3 now fails on a rule
  without one.
- **No documented claim.** The rule carried a one-line `meta.docs.description`
  and no docstring, no rationale and no measurement.
- **Shipped at `error` in both presets** — `src/index.ts` lines 123 and 219 at
  that commit.
- **The implementation is the whole rule**: inside a test file it reported
  *every* `typeof` unary expression and *every* `in` binary expression, with no
  further condition. `typeof x === "string"` is the ordinary way to write a type
  narrowing in TypeScript, so the population it flags is not a defect class.

A rule at `error`, with no test, no stated claim, and a predicate that matches
an idiom rather than a mistake, should not have shipped. That is sufficient
grounds on its own, and it is grounds anyone can re-check from the blob.

## The justification on record is not

#183's message groups this rule into "read at 50, 50, 39 and 25 findings with 0,
0, 0 and 3 true positives respectively" — positionally, **39 findings read, 0
true positives**.

That figure cannot be reproduced and is contradicted by later work: two
independent audits, over different corpora and with different criteria, put the
true-positive rate at **23.5%** and **41.3%**. At 41%, drawing 39 findings and
hitting zero has probability of order 1e-9. At least one of the three
measurements is wrong, and the one nobody can re-run is the one in the commit
message: the rule, its finding set, and any working notes are all gone, and no
evidence document was ever written.

**Do not cite "0 true positives" for this rule.** The deletion stands on the
structural grounds above, which are checkable. The precision claim is not.

## What this changed

This is the case that produced the evidence-retention gate. Two rules were
withdrawn in #183 on measured grounds; for one (SARJ061) the measurements were
deleted along with the rule, and for this one they were never written down. In
both, the number that justified the decision outlived every artifact that could
support it. `scripts/check-file-conventions.sh` §2b and §5 now make deleting an
evidence document a CI failure rather than a tidy-up.
