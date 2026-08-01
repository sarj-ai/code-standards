# `no-trailing-value-narration` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-trailing-value-narration.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Flag a trailing comment that spells out a literal already on the
line — the TypeScript twin of Python's SARJ051.

    staleTime: 5 * 60 * 1000, // 5 minutes

The comment adds one thing — the unit — and the line already carries every
number in it. Put the unit in the *name* (`STALE_TIME_MS`, a `Duration`
helper) and the fact travels with the value: it survives a copy-paste, it is
visible at every call site, and it cannot drift when someone edits the
arithmetic and forgets the comment. That drift is the whole risk — a wrong
unit comment is worse than none.

**The test is deliberately narrow.** Every one of these must hold: the code
before the comment contains a numeric literal; the comment contains at least
one number and EVERY number it contains appears verbatim in that code; and
every non-numeric word is either a unit word or already an identifier on the
line. So `// 5 minutes` over `5 * 60 * 1000` fires, while `// ~3.5 days` over
`300000` — a conversion the reader cannot do in their head — does not, and
neither does `// doubles per attempt, capped by the gateway`. A comment
carrying a ticket or URL is exempt (protected-class signal S1).

**Measured.** 18 hits across the nine-repo corpus, 18 of 18 true positives.
They cluster hard: one first-party analytics-hooks module
alone holds 12 `staleTime` lines, its sibling `lib/query-client.ts` two more,
and a first-party Worker config module carries
`export const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 90; // 90 days`.
