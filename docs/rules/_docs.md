# `_docs` — evidence

Every rule's documentation links are computed from its name. `_docs.ts` owns the
three constants (`REPO_BLOB`, `TESTS_DIR`, `EVIDENCE_DIR`) and the four
derivations built from them, and it exports `createRule` — `RuleCreator(evidenceUrl)`
— so a rule's `meta.docs.url` is the same derivation ESLint prints when it
reports.

## Why derived

Before this change every rule repeated three lines of `RuleCreator` boilerplate
with a hand-typed URL:

```ts
export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({ ... });
```

All 51 copies pointed at `sarj-ai/linting`. The repository is `sarj-ai/standards`
and has been for the whole life of the plugin, so every "See the rule docs" link
ESLint has ever printed for an `@sarj/*` rule was a 404. That is what a
hand-typed link does: it is correct on the day it is written and nothing ever
looks at it again. One derivation in one module cannot drift, and
`tests/rule-docs.test.ts` pins the derivation itself so swapping it back for a
string fails a test rather than rotting silently.

The links also moved target. They used to point at the rule's own source, which
is the thing the reader already has; they now point at the evidence document and
the tests, which are the two things the source deliberately no longer carries.

## The shape a rule module must have

```
/**
 * @fileoverview <name> — <one-line claim>
 *
 * Examples: <derived>/packages/typescript/tests/rules/<name>.test.ts
 * Evidence: <derived>/docs/rules/<name>.md
 */
```

Six content lines is the cap, with no budget file and no exemptions. The
mechanism is a direct port of `sarj-python-lint`'s, which took all 72 Python
rules to the same shape in PRs #178 and #182; the difference is that TypeScript
can derive `meta.docs.url` at runtime, so the derivation is load-bearing rather
than only test-checked.

## What a comment may still say

A comment may explain the code beneath it. It may not carry a measurement — a
count, a percentage, a `file.ts:12` citation, or the vocabulary of a corpus
sweep. `tests/rule-docs.test.ts` greps every comment in `src/rules/` for exactly
that and fails, which is what keeps the evidence in the document a reader can
choose to open instead of on the first screen of a file they were reading for a
different reason.
