# `no-positional-tuple-return` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-positional-tuple-return.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

TS port of SARJ026 (`prefer-namedtuple-over-tuple-return`). A
multi-field value returned across a module boundary should be an object with
named fields, not a positional tuple the caller has to unpack by position.

`export async function fetchDoc(): Promise<[string, Headers, string | null]>`
forces every call site to remember which slot is which, and the names live
only in the destructuring at the call site — so two call sites can and do
disagree. Returning `{ body, headers, contentType }` names each field once, at
the definition, and a wrong-field access becomes a type error instead of a
silently wrong value.

Fires on an *exported* function (or exported class method) whose declared
return type is a tuple of two or more elements — directly or wrapped in
`Promise<...>`. Exported means either the inline keyword (`export function
split`) or a detached specifier for the same module-scope binding (`export {
split }`, `export { split as s }`, `export default split`, `export = split`);
a re-export from another module and a type-only export do not count.

The permitted tuple uses are deliberately NOT flagged, matching the Python
rule's tuning plus the TS-specific idioms:

- **Homogeneous tuples** — `[number, number]`, `[Date, Date]`: a pair of the
  same thing (a range, a coordinate), not distinct fields.
- **Variadic tuples** — `[string, ...number[]]`: an immutable sequence, not a
  fixed record.
- **Labeled tuple members** — `[status: number, body: string]`: TypeScript
  surfaces those names at the call site, which is the whole point of the rule.
- **Discriminated tags** — `["ok", T]` with a literal first element: the tuple
  IS the discriminated union.
- **React hooks** — any `use*` function. `[value, setValue]` is the
  established contract of the entire hooks ecosystem; renaming at the call
  site is the intended affordance, not a hazard.
- **Accessor/mutator pairs** — a 2-tuple with a function type in either slot
  (`[T, (next: T) => void]`, `[() => void, Promise<void>]`). A function slot
  is a capability handle, not a data field. That is the
  same `[value, setValue]` contract without the `use` prefix, and every
  reactive library outside React ships it: measured on 2,186 real TypeScript
  files (zod / TanStack Query / react-router / swr / zustand), 2 of the 5 hits
  were this shape —
  query/packages/svelte-query/src/containers.svelte.ts:31 returning
  `[T, (newValue: T) => void]` and
  query/packages/query-persist-client-core/src/persist.ts:162 returning
  `[() => void, Promise<void>]` (unsubscribe handle + completion). Neither has
  "fields" to name; boxing them in an object would fight the ecosystem.
- Single-element tuples, unannotated returns, and non-exported helpers, whose
  two or three call sites live in the same file as the definition.

## Tier

High-volume and stylistic, the same treatment as `prefer-semantic-colors` and
`prefer-string-literal-union`. Measured on a 1,578-file third-party corpus: every
hit was the conventional `[value, cursor]` parser idiom, i.e. style rather than
defect. Promoted to `error` in strict since.
