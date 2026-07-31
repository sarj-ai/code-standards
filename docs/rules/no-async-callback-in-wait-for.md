# `no-async-callback-in-wait-for` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-async-callback-in-wait-for.test.ts).
This file holds what a test cannot carry: the false-positive family each guard
exists to stop, and the alternatives that were rejected.

`waitFor` polls its callback until the callback stops throwing. That contract is
built on a SYNCHRONOUS throw: testing-library invokes the callback, catches what
comes out, and retries. Make the callback `async` and it no longer throws — it
returns a rejected promise, which `waitFor` neither awaits nor inspects. The
assertion inside can fail on every poll and the test still passes.

```ts
// Reported: the rejection never reaches waitFor.
await waitFor(async () => expect(foo).toBe(true));

// Fine: the assertion throws where waitFor can see it.
await waitFor(() => expect(foo).toBe(true));
```

The failure mode is silent, which is why this is `error` in strict rather than
advisory: a test that cannot fail is worse than no test, because it is counted.

## Scope, and what each narrowing is holding back

- **Test files only.** `isTestFile(context.filename)` from `_paths.ts` gates the
  whole rule. `waitFor` is also an ordinary function name in production code — a
  poll helper, a queue drain — and there an `async` callback is normal.
- **A bare `waitFor` identifier callee only.** A member call
  (`page.waitFor(...)`, Puppeteer's) is a different API with a different
  contract, and its callback runs in the browser.
- **The FIRST argument only, and only a function.** `waitFor(promise)` and
  `waitFor(fn, { timeout })` are untouched; the second argument is options.
- **Arrow and function expressions.** A named function passed by reference is not
  followed: the rule has no type service, the binding may be re-assigned, and a
  false report here costs a real test rewrite.

## Alternatives rejected

- **`testing-library/no-await-sync-events` / `no-promise-in-fire-event`.** Both
  exist upstream and neither covers this position: they are about `fireEvent` and
  about awaiting a synchronous event, not about the `waitFor` callback's own
  asynchrony. `eslint-plugin-testing-library` has no rule for it.
- **Reporting the `await`s inside the callback instead of the callback.** The
  defect is the callback's signature, not any statement in it — an `async`
  callback with no `await` at all is equally broken, because it still returns a
  promise.
