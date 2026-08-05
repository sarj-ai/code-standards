# Concurrency and performance

Audit concurrency correctness and material performance problems using the shared [audit protocol](../README.md#audit-protocol).

## Judgment checks

- Blocking filesystem, network, subprocess, or database calls on an event loop.
- Independent operations awaited serially, unbounded fan-out, detached work without lifecycle/error ownership, or cancellation leaks.
- N+1 queries, repeated remote calls, unnecessary full materialization, and expensive work repeated in hot paths.
- UI main-thread work, unstable component definitions, and memoization that adds cost without evidence.

Distinguish correctness defects from optimization ideas. Require profiling, query evidence, or a clear complexity argument for performance-only findings.
