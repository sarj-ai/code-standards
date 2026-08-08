# Dead and duplicate code

Audit removable and duplicated code using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).

## Judgment checks

- Unreferenced modules, exports, branches, dependencies, feature flags, and compatibility paths.
- Near-duplicate business logic likely to drift when one copy changes.
- Wrappers, adapters, memoization, derived state, and helper layers that add no policy, safety, or meaningful reuse.
- Hand-rolled behavior already provided clearly by the standard library or an established dependency.

Account for reflection, plugin registration, framework conventions, public APIs, and generated entry points before declaring code dead. Prefer deletion over a new abstraction unless duplication is stable and meaningful.
