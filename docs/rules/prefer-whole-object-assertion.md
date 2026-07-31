# `prefer-whole-object-assertion` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/prefer-whole-object-assertion.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

`prefer-whole-object-assertion`. A run of consecutive `expect(...)`
statements that all pick at the *same* receiver is usually one assertion
written N times: `expect(user.id).toBe(1); expect(user.name).toBe("ada")`
fails on the first mismatch and never tells you about the second, and it
never says anything about the rest of `user`. Collapsing the run into one
`expect(user).toMatchObject({ id: 1, name: "ada" })` reports every mismatch
at once and reads as a single statement about the value.

## What the 2026-07 false-positive audit found, and what changed

The rule as originally written grouped a run on the receiver text ALONE. It
never looked at the matcher, and neither did its autofix. Measured over
25,508 deduped `.ts`/`.tsx`/`.js`/`.jsx` files (six first-party repos plus
zod, trpc, dub, openstatus, formbricks, documenso, unkey, midday, papermark,
cal.com and hono) it produced 3,148 findings. A seeded read of 37 of them
scored 0 true positives, 8 false positives and 29 arguable. Reconstructing
the class sizes over the population put the hard-false-positive share at
25.9%, consistent with the 21.6% read rate.

Three defects, in descending order of how much damage they did:

**1. The autofix was unsound.** It took `arguments[0]` of every assertion in
the run and emitted `<property>: <that argument>` into a `toMatchObject`,
whatever the matcher had been. Run through `Linter.verifyAndFix`, the shipped
build rewrote

- `expect(o.name).toContain("ab"); expect(o.items).toHaveLength(3);` into
  `expect(o).toMatchObject({ name: "ab", items: 3 })` — substring and length
  silently became equality;
- `expect(m.get).toHaveBeenCalledWith("k"); expect(m.set).toHaveBeenCalledWith("k", 1);`
  into `expect(m).toMatchObject({ get: "k", set: "k" })` — two spy assertions
  destroyed and an argument dropped;
- `expect(o.a).toBe(1); expect(o.a).toBe(2);` into
  `expect(o).toMatchObject({ a: 1, a: 2 })` — a duplicate key, so one
  assertion vanished;
- `expect(c.auth).toBe(auth); expect(c.zoho).toBe(zoho);` into
  `expect(c).toMatchObject({ auth: auth, zoho: zoho })` — `toBe` is
  `Object.is`, `toMatchObject` is recursive structural equality, so an
  identity check became a much weaker shape check.

Any repository that ran `eslint --fix` had its tests quietly weakened. The
four rewrites above are pinned as regression tests.

**2. It was scoped to neither tests nor hand-written files.** The module
imported nothing from `./_paths.js`, so a rule whose name begins "test"
happily reported on `export function f(o) { expect(o.a).toBe(1); expect(o.b).toBe(2); }`
in production code, and on generated files. This produced no *observed* false
positives on this corpus only because every `expect()` in it happens to sit in
a test file — it was a latent bug, not a measured win. `isTestFile` and
`isGeneratedFile` guards now close it.

**3. Runs were grouped across matchers `toMatchObject` cannot express.**
Population counts over the 3,141 sequences whose class could be reconstructed:

- spy/mock runs (`toHaveBeenCalled`, `toHaveBeenCalledWith`, …) — 238 (7.6%),
  e.g. `cal.com/packages/features/cache/decorators/__tests__/Memoize.test.ts:62`;
- DOM / testing-library runs — same receiver, same matcher, different
  expected values — 64 (2.0%), e.g.
  `trpc/packages/react-query/test/invalidateQueries.test.tsx:64`;
- runs containing a matcher with no object-literal equivalent (`toBeDefined`
  315 on its own, plus `toMatchInlineSnapshot`, `toBeInstanceOf`,
  `toHaveProperty`, `toBeGreaterThan`, `toBeCloseTo`, `toMatch`) — 484
  (15.4%), e.g. `cal.com/packages/embeds/embed-core/src/embed.test.ts:389`;
- a `.length` assertion mixed into element assertions — 26 (0.8%), e.g.
  `cal.com/packages/features/schedules/lib/date-ranges.test.ts:646`.

## The invariant the guard establishes

**The rule now reports a property run only where its own fix is exactly
equivalent to the code it replaces.** Concretely, every statement in the run
must be `expect(<pure receiver>.<identifier>).<M>(<primitive literal>)` with
`M` in `toBe` / `toEqual` / `toStrictEqual`, or `expect(...).toBeNull()`. On a
primitive literal those three matchers and `toMatchObject`'s per-key
comparison all agree, so the rewrite cannot change whether the test passes.
The property names must also be distinct — a duplicate key is what silently
deleted an assertion above — and must not be `length` or `size`, whose
receiver is a collection that `toMatchObject` cannot describe.

"Pure receiver" means an identifier, `this`, or a chain of member accesses
over one, never a call: `expect(getUser().a).toBe(1); expect(getUser().b).toBe(2)`
invokes `getUser` twice and the merged form invokes it once.

Deliberately dropped, with the recall cost stated rather than hidden:

- a run that mixes one un-mergeable matcher (typically `toBeDefined`) into
  otherwise mergeable `toBe`s no longer fires at all — part of 344 sequences.
  That is the honest price of the invariant, and those are exactly the runs
  whose autofix corrupted the suite;
- a non-literal expected value — `expect(c.auth).toBe(auth)` — is dropped
  even though it looks mergeable, because merging it is the `toBe`-to-
  structural-equality downgrade above. It was never a defect: there is no
  `toMatchObject` that says what those two statements say.

## Array-indexed runs get different advice, not silence

581 sequences (18.5%) group through an array — `expect(bodies[0]).toEqual(a);
expect(bodies[1]).toEqual(b)`, e.g. `hono/src/router/trie-router/node.test.ts:765`.
`toMatchObject` was always the wrong advice there. These keep firing under a
separate message: a per-element run asserts nothing about the array's
*length*, so `bodies` may hold extra elements and the test still passes, and
the fix is `expect(bodies).toEqual([a, b])`. That is a real weak-assertion
defect on its own terms, independent of the merge argument, which is why it
survives rather than being suppressed. It fires only when the indices are
exactly `0..n-1` (otherwise the leading elements are unconstrained and the
array literal would be a guess) and every matcher is the same `toEqual` or
`toStrictEqual`. It is **not** autofixed: the rewrite adds a length
assertion, so it is a deliberate strengthening, not an equivalence, and a
strengthening must be a human's decision.

Only 34 of those 581 survive the "indices are exactly `0..n-1`, one matcher
throughout, statements adjacent" predicate. The rest index from 1, skip an
index, or interleave another statement, and for those there is no array
literal to suggest — so they are dropped rather than given advice the rule
cannot substantiate.

## Known false negatives (limits, not guards)

The rule only ever recognised the Jest/Vitest `expect(x).matcher(y)` shape
hanging directly off `expect`. It silently ignores chai
`expect(x).to.equal(y)`, `assert.equal(...)`, `await expect(...)`
(Playwright), `expect.soft(...)` and every `.not.` / `.resolves` / `.rejects`
chain — and a `.not.` in the middle of a run breaks the run, suppressing the
report for the statements around it. These are recorded as limits; none of
them is a false positive.

Result over the same 25,508-file corpus: 3,148 findings before, 945 after
(911 `combineAssertions`, 34 `assertArrayOnce`) — a 70% cut. That is a large
number to give up, and it is the right one: the audit's read sample scored
**zero** true positives in 37 findings, so what was removed was not a
population of caught defects, it was a population of runs the rule could not
describe and whose autofix it could not perform. What is left is the subset
where the rule's own recommendation is provably the same test.

## Evidence relocated from the source

### `}`

The statement as a mergeable assertion, or `null` when it is anything
else — which also terminates whatever run was in progress. Everything the
audit found in the false-positive classes fails here: a spy matcher, a
`toBeDefined`, a `.not.` chain, `await expect(...)`, `expect.soft(...)`,
chai's `.to.equal`, or an expected value that is not a literal.


## `__proto__`: the autofix silently deleted an assertion

The guard above ("the rule reports a property run only where its own fix is
exactly equivalent to the code it replaces") had one hole, and it was the
sharpest possible instance of the invariant it claims.

Input, in a test file:

```ts
it("proto", () => { expect(o.__proto__).toBe(null); expect(o.b).toBe(2); });
```

`--fix` output, from the shipped build:

```ts
it("proto", () => { expect(o).toMatchObject({ __proto__: null, b: 2 }); });
```

`__proto__:` in an object literal is the prototype SETTER, not a property
definition. `Object.keys({ __proto__: null, b: 2 })` is `["b"]`, so
`toMatchObject` checks `b` and nothing else — the `__proto__` assertion is gone.
Quoting does not help: per the spec `"__proto__": v` is the same production, and
only a computed key `["__proto__"]` would define an own property.

Verified under vitest with `const o = Object.create({ marker: 1 }); o.b = 2;` —
the original pair THROWS and the rewritten form PASSES. `COLLECTION_PROPERTIES`
excluded `length` and `size` but not this.

This is the same class PR #183 was written to eliminate. It survived because
every test covered the REPORT and none applied the FIX; the applied-fix suite in
`tests/rules/prefer-whole-object-assertion.test.ts` now pins the language fact,
the fixer's output, and the runtime consequence.

**Audited for siblings.** `constructor`, `toString`, `valueOf`,
`hasOwnProperty` and every other inherited name ARE plain own keys in an object
literal, and jest's `subsetEquality` walks the prototype chain when reading them
off the received value, so those merge faithfully. `get x() {}` / `set x() {}` /
`async x() {}` are different PRODUCTIONS, not different key names, and this
fixer only ever emits `key: value`. `__proto__` is the only name in the language
whose meaning changes between a member expression and a literal key.

A `__proto__` assertion now BREAKS the run rather than poisoning it, so
`expect(o.__proto__).toBe(null); expect(o.b).toBe(2); expect(o.c).toBe(3);`
still merges `b` and `c` and leaves the prototype assertion alone.

Corpus effect: 4 findings withdrawn over 32 OSS TypeScript repos / 145,235
files.

## Comments inside the run: the report stands, the fix is withheld

The fixer replaced the first statement and `fixer.remove`d the rest, which takes
each removed statement's text but not the comment above it. The comment is left
dangling over the merged assertion, describing a statement that no longer
exists. Worst case that dangling line is an
`// eslint-disable-next-line @sarj/prefer-whole-object-assertion`, which then
becomes a fresh `reportUnusedDisableDirectives` error the author never wrote.

Deleting a comment is also not "exactly equivalent to the code it replaces", so
the rule now reports without a fix whenever a comment sits inside the span it
would rewrite — between two statements of the run, or inside one of them. A
comment before the first statement or after the last is outside the span and
survives, so the common `// setup` / trailing-comment shapes still autofix.
