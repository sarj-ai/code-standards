# `no-tautological-expect` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-tautological-expect.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

TS side of SARJ057 (`no-tautological-expect`). An `expect(...)`
whose operands are all literals has already decided its outcome before the
test runs: `expect(true).toBe(true)` passes if you delete the entire module
under test. It is not a weak assertion, it is a *non*-assertion.

This is the placeholder that never got replaced. Every hit found in the
first-party sweep is one:

- a worker's handler test — `expect(true).toBe(true); // placeholder`, in a
  suite whose name promises it disambiguates customer records,
- a `dummy.test.ts` in a shared node package — `expect(true).toBe(true)`,
- a `dummy.test.ts` in its isomorphic sibling package — `expect(1).toEqual(1)`.

The Python side (SARJ043 `zero-assertion-test`) has caught the assertion-free
version of this since 0.15.0 and has no TypeScript counterpart, which is
precisely why that first placeholder went uncaught for as long as it
did: the file *has* an assertion, so nothing was looking at it.

Fires on exactly two shapes:

1. `expect(<literal>).toBe|toEqual|toStrictEqual(<textually identical literal>)`;
2. `expect(<literal>).<zero-argument matcher>()` — `toBeDefined`,
   `toBeTruthy`, `toBeNull`, `toBeUndefined`, `toBeFalsy`, `toBeNaN`. With a
   literal receiver the answer is fixed at parse time either way.

**The narrowness is the rule.** The obvious generalisation — "flag a
comparison of a thing with itself" — was measured across five repositories
and is ~95% false positives. `expect(hash([o])).toEqual(hash([o]))` is a
*determinism* test; `expect(memo(x)).toBe(memo(x))` is a *memoization* test;
`expect(a).toEqual(a)` on a value with a custom equality is a *reflexivity*
test. All three can genuinely fail, and all three are correct code. So an
operand that is an identifier, a member expression or a call is never enough:
both sides must be literals, and textually identical ones.

Deliberately NOT flagged:

- any modified chain — `expect(x).not.toBe(...)`, `.resolves`, `.rejects`.
  The matcher must hang directly off the `expect(...)` call, which keeps the
  rule to the shape it can reason about;
- a literal compared with a *different* literal (`expect(1).toBe(2)`) — that
  assertion always fails, which is loud on the first run rather than silent;
- a spread element anywhere in an array/object literal (`expect([...xs])`),
  whose contents come from a runtime value;
- a template literal with interpolations, for the same reason;
- anything outside a test file.

Measured before shipping: 3 hits across 5,819 `.ts`/`.tsx` files (1,003 of
them test files, where the rule is active) — six first-party repos plus
got / hono / swr / trpc. 3 true positives,
0 false positives; all three are the placeholders listed above.

## Evidence relocated from the source

### `case AST_NODE_TYPES.UnaryExpression:`

True when `node` is written entirely out of literals — no identifier, member
expression, call or spread anywhere inside it. That exclusion is the whole
false-positive guard: a value the code produced is what makes an assertion an
assertion.

