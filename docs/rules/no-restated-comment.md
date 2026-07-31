# `no-restated-comment` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-restated-comment.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Flag a one-line comment that only re-spells the statement
beneath it — the TypeScript twin of Python's SARJ049.

    // Login schemas
    export const ZLoginResponseSchema = z.object({ … });

Every content word of the comment is already an identifier on the line below.
It cannot go out of date usefully, only silently, and a reader who scans it
learns nothing the code did not already say. Delete it, or replace it with the
*why*.

**Division of labour with `no-comment-cruft`.** That rule already reports the
VERB-LED shape (`// increment the counter` above `counter += 1`), corroborated
against the statement *head*. This rule defers to it — `restatesStatementHead`
is imported and used as an exemption — so a comment is never reported twice.
What is left for this rule is the noun-phrase label whose every word appears
anywhere on the line: `// Env badge`, `// OTP schemas`,
`// Language enum`.

**What makes it safe.** The first attempt at this shape (PR #98) corroborated
by substring — `service` matched `locationService` — and produced 933 hits at
a ~60% false-positive rate. Coincidental token overlap is the failure mode, so
every guard below is load-bearing: zero information (EVERY content token must
appear, exact or stemmed, never by prefix); at least two content tokens (one
word labels a thing, it does not restate a statement); a single-line comment
(a `//` run is a paragraph); a single-line, value-producing statement (a
comment above a block labels a region); the statement must invoke something
(a comment above a plain data declaration is a group label — that one shape
was every false positive left in the Python corpus sweep); and the whole
nine-signal protected class from `_comments` is exempt.

**Measured.** 1 hit across the five maintained repos (four of them 0, the
fifth 1) and 8 across zod / swr / TanStack
Query, of which one — zod's `// no issues with confirmPassword or password`
over `return payload.issues.every(…)` — was the last false positive and is
now guarded by `NEGATION_WORD_RE`. The single-line-statement requirement is
what keeps the first-party count at zero: a `// Env badge` comment sits
over a multi-line `const renderEnvBadge = () => (`, i.e. it labels
a REGION, so this rule leaves it to `no-comment-cruft`'s section-label check.
That makes it a preventive ratchet on TypeScript with essentially no
migration cost, unlike its Python twin (SARJ049, 29 hits in one first-party
repo).

## Evidence relocated from the source

### `a`

Four shapes that pass the zero-information test and were wrong every time in
the famous-corpus sweep: modality (`can`, `should`, `must` state a
possibility or an obligation, which no arrangement of identifiers can say), a
colon-terminated lead-in (it announces what follows rather than describing the
line under it), inline emphasis (someone who wrote `*not*` or backticked an
identifier was making a point about it), and a bare negation — `no`/`not`/
`never` are stopwords for the tokenizer, so a comment stating a NEGATIVE
property passes against the positive spelling below it (`// no issues with
confirmPassword or password` over `return payload.issues.every(…)`,
zod/packages/zod/src/v4/classic/tests/refine.test.ts:546). Saying what is
absent is the one thing the code's own words cannot.

### `/** True when `a` and `b` are `//` comments on consecutive l`

The statement must *do* something. A comment above a plain data declaration
labels the datum, and that shape is a series of group labels rather than
narration — it was every false positive left in the Python corpus sweep.

### `}`

Walk out to the STATEMENT, not merely to the first node starting on that
line. Stopping early looked at the innermost `Identifier`, whose parent
is an expression rather than a block, so the sibling test silently never
ran — zod's `assignability.test.ts` alone contributed 89 hits, a table
of one-line `z.string() satisfies z.core.$ZodString;` assertions each
labelled with the type it checks.

