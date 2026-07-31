# `no-restated-jsdoc` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-restated-jsdoc.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Flag a JSDoc block whose every word is already in the signature
it documents.

    /** Get the user by id. */
    export function getUserById(id: string): User { … }

The block costs three lines and a review, survives every rename that matters,
and tells the reader nothing. Delete it, or say what the caller cannot read
off the name: what it throws, what it assumes, why it exists.

**The generated-file sniff is mandatory, not a nicety.** In the 817-block
hand-written JSDoc corpus, 87% of the raw hits for this shape came from
OpenAPI codegen output, where every `@param id The id.` is emitted by a
template and rewritten on the next `openapi-generator` run. Editing them is
work that gets reverted; `isGeneratedFile` (path AND header marker) is what
takes the count from "hundreds, mostly noise" to a readable handful.

**Never flagged**: a block carrying a value tag (`@deprecated`, `@see`,
`@example`, `@throws`, `@template`, `@remarks`, `@since`, …) — those are the
content the signature cannot hold; a block carrying any tag this rule does not
model, because it cannot judge what it cannot read; a `@param` or `@returns`
description that adds a word of its own; and anything in the nine-signal
protected class from `_comments`.

**Autofix is deliberately a SUGGESTION, never `--fix`.** Deleting a doc block
in bulk is silent information loss if the judgement is wrong once; a
suggestion makes a human accept each one.

**Measured.** 40 hits across the five maintained repos (11 in one, 29 in
another, 0 in the remaining three) and 5 across zod / swr / TanStack Query
(zustand 0). All 45 were read; the only debatable one is zod's
`/** The input data */` on `readonly input: unknown`, which is a published
API doc that nonetheless says nothing the field does not. Everything else is
`/** Logout function */` on `useLogout`, `/** Base64 encode a string */` on
`base64Encode(str)`, `/** A list row. */` on `ListRow`.
