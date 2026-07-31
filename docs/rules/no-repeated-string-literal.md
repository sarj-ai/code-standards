# `no-repeated-string-literal` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-repeated-string-literal.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

TS port of SARJ024 (`no-repeated-string-literal`). The same long,
*structured* string repeated across two or more functions of a module is a real
maintenance hazard: when one copy is edited the others silently drift. A column
list that gains a column in the read query but not in the upsert, or a prompt
template updated in one branch only, fails at runtime and nowhere else.

COUNT THRESHOLD — CONVERGED WITH SARJ024 (2026-07). This rule and the Python
twin had drifted to two different definitions of "repeated": TS demanded three
total occurrences, Python only two distinct enclosing functions. A literal used
exactly twice therefore fired in `.py` and was clean in `.ts`, which is a
defect — the same code judged differently by file extension. Both were measured
and TS moved to Python's rule; **"two distinct functions" is the only count
threshold.** Evidence:
  - Requiring three occurrences would drop 15 of the 18 findings over the
    first-party Python corpora (the `python/` and `sdks/python` trees of one
    repo, plus one back-end repo) and
    the django/fastapi/celery FP controls, and the dropped ones are true
    positives of exactly the shape this rule exists for:
    one first-party store module repeats one
    `SELECT stage FROM signup_profiles WHERE signup_token = %s FOR
    UPDATE` verbatim between two sibling submit methods, and a second store
    module repeats a
    10-column `SELECT … JOIN plan_types …` between two methods. Two copies is
    where column-list drift *begins*; the third was arbitrary.
  - Dropping the gate costs the TS side nothing. Over 748 first-party TS/TSX
    files (the `typescript/` and `sdks/typescript` trees of one repo, plus
    one front-end repo) the rule yields
    0 findings at BOTH thresholds. Over the 2,186-file third-party corpus
    (zod / TanStack Query / react-router / swr / zustand) it yields 0 at three
    and 5 at two — and all 5 were react-router `*-test.ts` fixtures that the
    test-file exemption should already have covered but did not, because
    `_paths.isTestFile` only knew the `.test.ts` spelling. That gap is fixed at
    its source, so the corpus delta of this change is 0 → 0 everywhere.
Precision here is carried by the *structured* filter below, not by counting.

The rule is deliberately narrow — it fires only where cross-site drift is a
genuine bug, never on coincidentally-equal prose. Three filters combine:

1. **Structured only.** A literal qualifies only if it carries structural
   signal that makes coincidental equality near-impossible: it contains a
   newline (multi-line SQL / prompt templates), it matches an *uppercase* SQL
   keyword (`SELECT`, `FROM`, `ON CONFLICT`, ...) — matched case-sensitively so
   English prose does not trip it, only real SQL does — or it is a bare
   snake_case / dotted identifier, i.e. a constraint / index / column-list name
   reused across statements. Plain user-facing messages and log lines carry
   none of these, so two same-text-different-intent messages are never coupled
   into one shared constant.
2. **Cross-function only.** Occurrences must span at least two distinct
   enclosing functions. Two uses inside one function are edited together and
   hoisting them buys no drift protection — that is pure locality loss. This
   is the only count threshold; see the note above.
3. **Exclusions.** Template literals *with* substitutions (the f-string
   analogue — each fragment is half a sentence, not a reusable value), import
   and `require` sources, JSX attribute values (a repeated Tailwind class list
   is `no-duplicate-class-names` territory, not a drift bug), and test files,
   where fixtures legitimately repeat literal payloads.

A substitution-free template literal IS included: in TypeScript that is just a
multi-line string, and it is exactly where embedded SQL lives — but only when
it is UNTAGGED (see below).

Every occurrence after the first is reported, so a deliberate duplicate can be
disabled on its own line.

CORPUS SWEEP (2220 files across zod / TanStack Query / react-router / swr /
zustand, 2026-07): 96 raw hits, 100% of them the quasi of a TAGGED template
and every one a false positive. Two families:
  - 94 in react-router's Playwright suites, where `js`…`` is the SOURCE TEXT of
    a scratch app the test writes to disk
    (`react-router/integration/single-fetch-test.ts:1482` repeats a 3-line
    `app/routes/target.tsx` fixture). Hoisting a shared constant would move the
    fixture away from the assertion that explains it — and the fixtures are
    MEANT to be near-identical; that is what makes the assertions comparable.
  - 2 in `query/packages/query-devtools/src/Devtools.tsx:398`, where ``css`…` ``
    is a goober style block whose "duplicate" is a style rule, i.e. exactly the
    styling-string category `isScaffolding` already excludes for JSX attributes.
A tagged template is an INVOCATION, not a string value: the tag decides what
the text means, so "these two strings must not drift" is not a claim the rule
can make about it. Tagged templates are therefore excluded. An untagged
multi-line SQL/prompt literal — the shape the rule exists for — still fires.
