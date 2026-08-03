# Concurrency and performance

Audit concurrency correctness and material performance problems using the shared [audit protocol](../README.md#audit-protocol).

## Automated baseline

Run applicable rules such as `no-sequential-await`, `no-silent-promise-catch`, `no-async-callback-in-wait-for`, `inefficient-string-concat-in-loop`, `no-string-concat-in-loop`, and configured async linters.

## Judgment checks

- Blocking filesystem, network, subprocess, or database calls on an event loop.
- Independent operations awaited serially, unbounded fan-out, detached work without lifecycle/error ownership, or cancellation leaks.
- N+1 queries, repeated remote calls, unnecessary full materialization, and expensive work repeated in hot paths.
- UI main-thread work, unstable component definitions, and memoization that adds cost without evidence.

Distinguish correctness defects from optimization ideas. Require profiling, query evidence, or a clear complexity argument for performance-only findings.
