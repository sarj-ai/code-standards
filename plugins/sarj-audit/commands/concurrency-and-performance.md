# Concurrency and performance

Audit concurrency correctness and material performance problems using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).

## Judgment checks

- Blocking filesystem, network, subprocess, or database calls on an event loop.
- Independent operations awaited serially, unbounded fan-out, detached work without lifecycle/error ownership, or cancellation leaks.
- N+1 queries, repeated remote calls, unnecessary full materialization, and expensive work repeated in hot paths.
- UI main-thread work, unstable component definitions, and memoization that adds cost without evidence.

Distinguish correctness defects from optimization ideas. Require profiling, query evidence, or a clear complexity argument for performance-only findings.

## Adjacent eager array passes

Inspect adjacent `filter`/`map` and `map`/`filter` passes for material intermediate
allocation on large or hot collections. Report a performance defect only with
profiling, scale evidence, or a concrete complexity argument; otherwise label
fusion as an optimization suggestion. Two linear passes remain linear.

```ts
// Synthetic example: collect prices for available products.
const prices = Object.fromEntries(
  products
    .filter(product => product.available)
    .map(product => [product.sku, product.price]),
);

// After: collect the same entries in one traversal.
const entries: [string, number][] = [];
for (const product of products) {
  if (product.available) {
    entries.push([product.sku, product.price]);
  }
}
const prices = Object.fromEntries(entries);
```

The example assumes a dense array and pure callbacks that do not depend on
indexes or the callback's array argument. Preserve callback order, exception
timing, `thisArg`, sparse-array behavior, and truthiness filtering. A fused
callback runs mapping before later filtering callbacks; side effects can make
that observably different. Preserve duplicate-key last-write behavior when
building objects, including keys such as `__proto__`; plain object assignment is
not interchangeable with `Object.fromEntries` for arbitrary keys.

Use iterator helpers only when the supported runtimes provide them; TypeScript
library declarations do not supply a polyfill. `flatMap` creates wrapper arrays
in common filtering rewrites and is not automatically faster. Measure the
proposed replacement before claiming a speedup.
