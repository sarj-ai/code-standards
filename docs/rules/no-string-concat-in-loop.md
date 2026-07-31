# `no-string-concat-in-loop` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-string-concat-in-loop.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Disallow string accumulation via `+=` inside a loop, which is
the classic O(n^2) string-building antipattern: each `+=` rebuilds the whole
string. Push the parts onto an array and `arr.join("")` after the loop
instead.

This is a purely SYNTACTIC rule — it uses scope analysis (not the type
service) to confirm the left-hand side was declared with a string-literal
initializer (`let s = ""`, `= "..."`, or a template literal). It is
deliberately conservative: when the initializer type cannot be determined
(no initializer, a non-literal expression, a parameter, etc.) the `+=` is
NOT flagged. This mirrors the Python rule SARJ002.

Both the compound `s += x` and the equivalent longhand `s = s + x` (a plain
`=` assignment whose RHS is a `+` `BinaryExpression` with the target as one
operand) are detected — they have identical O(n^2) behavior. A plain
`s = x + y` (target absent from the RHS) is NOT flagged.

AT MOST ONE REPORT PER (accumulator, loop). A single loop that appends in
several branches is ONE defect with ONE fix — replace the accumulator with an
array of parts — so N reports on it are N-1 copies of the same finding, and
silencing it costs N disable comments. Corpus sweep (2220 files across zod /
TanStack Query / react-router / swr / zustand, 2026-07): 62 raw reports
collapsed to 21 distinct defects. `react-router/packages/react-router-fs-routes/flatRoutes.ts`
alone produced 23 reports; `react-router/packages/react-router/lib/server-runtime/cookies.ts:221-231`
produced 6, all of them the one percent-encoder loop appending `result` from
four branches. This matches the one-report-per-loop policy `no-sequential-await`
already follows.

EXEMPTION — AN ACCUMULATOR DECLARED INSIDE THE LOOP BODY, from a first-party
review regression.
The O(n^2) claim requires the accumulator to survive across iterations. A
`let s = "..."` declared *inside* the body is rebound to a fresh string every
pass, so the `+=` runs a bounded number of times on a string that is discarded
at the end of the iteration — there is no quadratic growth for `join` to
remove, and the parts are typically already being collected into an array.
Evidence: one first-party editor-serializer site,
where `let sectionText = \`## ${…}\`` is declared in the body, appended to at
most once behind an `if (body)`, and then pushed onto `textParts` for a
`textParts.join()` after the loop. The disable there reads "single conditional
append to a per-iteration string; result is collected via textParts.join below,
not O(n²)" — the rule had nothing to offer.

The Python twin SARJ002 (`inefficient_string_concat_in_loop`) has drawn this
same line since it shipped: "A target that is freshly (re)bound earlier in the
same loop body … is loop-local: it starts empty each iteration, so the growth
is bounded, not cross-iteration accumulation." The two rules now agree.

## Evidence relocated from the source

### `// The O(n^2) claim requires the accumulator to SURVIVE acro`

Only flag when we can confirm the LHS was string-initialized; a
numeric initializer (or anything non-string) is intentionally
excluded to avoid false positives.

