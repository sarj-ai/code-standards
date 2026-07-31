# `require-assert-never` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/require-assert-never.test.ts).
This file holds what a test cannot carry: the false-positive family each guard
exists to stop, and the alternatives that were rejected.

A `switch` over a discriminated union is exhaustive only for as long as nobody
adds a member. `assertNever(value)` in the `default` clause makes that a COMPILE
error: the parameter is typed `never`, so a union member the switch does not
handle no longer narrows away and the call fails to typecheck. Without it, adding
a member silently routes through `default` and the new case does nothing.

The rule fires on a `switch` that HAS a `default` clause which neither calls
`assertNever` nor does any runtime work. It does not demand a `default` from a
switch that has none — that is a separate opinion, and a noisier one.

## The four guards, and what each is holding back

The rule is purely syntactic. It has no type information, so it cannot tell a
switch over a union from a switch over a config string, and every guard exists
because injecting `assertNever` into the wrong one throws at runtime.

1. **An explicit `assertNever(...)`, in any position.** Bare
   (`assertNever(kind)`), namespaced (`utils.assertNever(kind)`), thrown
   (`throw assertNever(kind)`), returned, or inside a block-scoped default
   (`default: { assertNever(kind); }`). Recognising only the bare expression
   statement would have reported the canonical `throw assertNever(x)` spelling.

2. **A default that does real runtime work.** A reducer's `return state`, an
   HTTP-status `return fallback()`, a `break`, a `throw`, a log call, an `if`.
   The clause is handling the case, and `assertNever` there would be wrong: the
   author is deliberately accepting values outside the union.

3. **A fallthrough default.** An empty `default:` that is not the last clause
   hands control to the case below it, which does the work. There is nothing to
   assert, and reporting it would ask the author to break the fallthrough.

4. **A comment-documented no-op.** `default: // nothing to do`, or an empty block
   containing a comment. This is the load-bearing one: a bare empty `default` is
   indistinguishable from a config-string switch whose author meant "ignore
   anything else", and a rule with no type service must not turn that into a
   runtime throw. A written intent is honoured; a bare, undocumented empty
   default is not.

## Alternatives rejected

- **Require a `default` on every switch.** Most switches in a codebase are over
  strings or numbers, not unions, and a mandatory `default` on those is noise
  plus a dead branch.
- **Use the type service to detect a union discriminant.** Rejected for cost:
  this rule runs at `error` in the `strict` preset over whole repositories, and
  the syntactic form plus guard 4 reaches the same verdict wherever the author
  has said what they meant. `@typescript-eslint/switch-exhaustiveness-check` is
  the type-aware complement for anyone who wants it, and it does not subsume this
  rule: it says nothing about a `default` clause that silently swallows a new
  member.
- **Autofix by inserting `assertNever`.** On a non-union discriminant the fix
  compiles and then throws in production. The rule reports and leaves the edit to
  a human.
