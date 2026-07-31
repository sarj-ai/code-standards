# `no-unsafe-mock-casting` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-unsafe-mock-casting.test.ts).
This file holds what a test cannot carry: the false-positive family each guard
exists to stop, and the alternatives that were rejected.

`myFn as Mock` is an ASSERTION, not a check. TypeScript takes the author's word
that the import was mocked, so the cast keeps compiling after the
`vi.mock("./module")` above it is deleted, after the import is repointed at the
real module, and after the mocked function's signature changes. The test then
calls `.mockResolvedValue(...)` on the real function and fails at runtime with
"not a function" — or, worse, asserts against a real implementation nobody meant
to exercise.

`vi.mocked(myFn)` / `jest.mocked(myFn)` are typed helpers: they preserve the
function's own signature, so `mockResolvedValue` is checked against the real
return type, and an argument-count change in the module under test breaks the
test at compile time instead of at assert time.

```ts
// Reported.
const m = myFn as Mock;
const m = myFn as vi.Mock;
const m = <jest.Mock>myFn;

// Fine.
const m = vi.mocked(myFn);
const m = jest.mocked(myFn);
```

## Scope, and what each narrowing is holding back

- **Three type names: `Mock`, `MockInstance`, `SpyInstance`.** These are the
  spellings `vitest` and `jest` ship. A project's own `MyCustomMock` is left
  alone — it is not one of these APIs and has no `mocked()` counterpart.
- **Both the bare and the qualified spelling.** `Mock`, `vi.Mock`, `jest.Mock`
  and `vitest.MockInstance` all reach the same defect; matching only the bare
  identifier would miss the namespaced form, which is the more common one.
- **Both assertion syntaxes.** `x as T` (`TSAsExpression`) and the legacy `<T>x`
  (`TSTypeAssertion`).
- **Generated files are skipped**, via the shared `isGeneratedFile` predicate. A
  generated harness is not a file anyone edits.

## Alternatives rejected

- **`@typescript-eslint/consistent-type-assertions` with
  `assertionStyle: "never"`.** It bans every assertion, which is a different and
  much larger change; this rule is the part of it a test file cannot argue with.
- **Autofixing `x as Mock` to `vi.mocked(x)`.** The correct helper depends on
  which runner the file uses, the import may need adding, and the surrounding
  expression may already be a member chain. A report naming the right helper is
  enough.
