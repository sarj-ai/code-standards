# `prefer-module-level-constant` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/prefer-module-level-constant.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Flag a literal-only constant collection (or regex) declared
INSIDE a function body that should be hoisted to module scope.

Rationale — this is the single most frequent recurring review comment in the
mined PR corpus (~37 distinct PRs, TypeScript and Python alike): a lookup
table, allow-list, `Set` membership test or validation regex written at the
top of a function, rebuilt on every single call. Three costs, in increasing
order of severity:

1. Allocation — every call re-walks the literal and re-allocates the array /
   object / Set / Map. In a hot path or a React render this is pure waste.
2. Identity churn — a fresh object every call means a fresh reference every
   render, which silently defeats `useMemo`/`useEffect` dependency arrays and
   `React.memo` on anything the value is threaded into.
3. Discoverability — a domain constant buried in a function body is invisible
   to the next reader and cannot be exported, tested, or reused, so it gets
   duplicated in the next function that needs it. That is the defect class:
   the duplicated copies drift apart.

This rule is deliberately NOT a duplicate of `unicorn/consistent-function-scoping`,
which is enabled at error in the shipped strict config. That rule reports
nested FUNCTION declarations that reference nothing from their enclosing
scope; its entire visitor surface is the function node types and it never
looks at a `VariableDeclarator` whose init is an array, object, `new Set`,
`new Map` or a regex. The two rules are disjoint by construction.

What fires — a `const` binding inside a function whose initializer is one of:

  - an array literal, an object literal, `new Set([...])`, `new Map([...])`,
    or `Object.freeze(...)` around any of those, with at least `minElements`
    entries and where EVERY leaf is a literal; or
  - a regular-expression literal without the `g`/`y` flags.

"Every leaf is a literal" means string/number/boolean/null, an unsigned or
negated numeric literal, a template literal with no interpolation, or a
nested array/object of the same — no identifiers, no calls, no member
expressions, no spreads, no computed non-literal keys, no shorthand
properties. That single condition is what makes the hoist provably safe and
is also what eliminates the largest false-positive class outright.

False positives handled explicitly:

  - **Closes over a parameter or an outer binding.** `new Map([[userId, 1]])`
    or `[prefix + "-a"]` contains an identifier / a computed value, so it is
    not literal-only and never fires. Hoisting those would be a compile error
    or a behaviour change, so the literal-only gate is load-bearing, not a
    stylistic preference.
  - **Deliberately fresh per call because someone mutates it.** Every
    reference to the binding must be a provably non-mutating read: a member
    read, a call to a known non-mutating method, `for…of` iteration, or a
    spread into a NEW literal or argument list (which copies). A call to
    `.push`/`.set`/`.add`/`.sort`/`.splice`/…, an index or property
    assignment, a `delete`, or an `X++` bails immediately.
  - **Escaping value the CALLER may mutate.** Returning the binding, passing
    it bare as an argument, aliasing it into another variable, or embedding it
    in a returned object/array all bail. Once the value leaves the function
    this rule cannot see what happens to it, and a shared hoisted array that a
    caller mutates is a genuine cross-call data-corruption bug — exactly the
    kind of defect a lint rule must not introduce. Reads from an escaping
    CLOSURE are fine and still fire: a nested arrow that only reads the
    constant is unaffected by hoisting.
  - **Tiny literals where hoisting hurts readability.** A one- or two-element
    literal reads better next to its use, so `minElements` (default 3) sets
    the floor and can be raised per repo.
  - **Stateful regexes.** A `/…/g` or `/…/y` regex carries `lastIndex` across
    calls to `.test()`/`.exec()`. Hoisting one changes behaviour — the second
    call resumes mid-string — so global and sticky regexes are never reported
    even though they are the most expensive to recompile. This check used to
    apply only to a TOP-LEVEL regex literal: an ARRAY of regexes went through
    `isLiteralOnly`, where a `RegExpLiteral` is just an `AST_NODE_TYPES.Literal`,
    so `const patterns = [/a/g, /b/]` was recommended for hoisting and the
    hoist would have changed behaviour. `isLiteralOnly` now rejects a stateful
    regex at any depth. A stateLESS nested regex still qualifies.
  - **Test files.** Fixture tables inside a test body are local by design and
    hoisting them separates the data from the assertion that explains it.
    Exempt by default via `ignoreTestFiles`.
  - **Generated files** (`*.gen.ts`, `**/generated/**`, `*.d.ts`, or a
    `@generated` marker) opt out, matching `no-enum` and `no-zod-native-enum`.

There is no autofix. Hoisting has to pick an insertion point and may collide
with an existing module-scope name; both are judgement calls that belong to a
human, and a wrong automated hoist is worse than the warning.

SECOND SWEEP (25,508 deduped TS/TSX files across zod / trpc / dub /
openstatus / formbricks / documenso / unkey / midday / papermark / cal.com /
hono plus six first-party repos, 2026-07): 531 hits, 40 read in a seeded
random sample — 27 true positives, 1 false positive, 12 arguable. At a 2.5%
false-positive rate the rule is clean, and the single class found was drift:
it shipped its OWN test-path list instead of the shared `isTestFile`, so
`.e2e.ts` suites and `playwright/` fixture tables were not exempt — 13 / 531,
e.g. `cal.com/apps/web/playwright/booking-limits.e2e.ts:123`. Delegating to
`isTestFile` (plus `isStoryFile`, which carries the `*.stories.*` case the
local list also held) is a strict superset of the old patterns.

CONFIRMED AND NOT TO BE CHANGED: the rule never fires on a value that closes
over a parameter or a prop. `isLiteralOnly` structurally rejects Identifier,
MemberExpression, CallExpression, spread, shorthand and computed non-literal
keys, so `new Map([[userId, 1]])` and `[prefix + "-a"]` cannot reach a report.
That gate is load-bearing, not stylistic; do not relax it to raise the count.

## Provenance

Mined from two years of PR review (SARJ-928) — the single most frequent
uncovered theme, ~37 distinct PRs. Measured 17 hits / 1085 real TS files, all
true positives, so it is safe to run everywhere.
