# Service boundaries and dependency injection

Audit separation of concerns and dependency direction using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol). This command incorporates the former dependency-injection audit.

## Judgment checks

- Handlers or UI components containing business policy, persistence queries, or direct third-party orchestration.
- Services constructing concrete databases, clients, queues, caches, or sibling services rather than receiving dependencies at a composition root.
- Domain logic coupled to framework request/response, ORM, or transport types.
- God services with unrelated responsibilities or pass-through layers that add no policy.
- Scattered persistence or remote-access code without a coherent boundary.

Do not require a class, interface, or service layer for pure functions, trivial CRUD, framework-provided dependencies, or a single stable implementation when added abstraction would not improve testing or substitution.

## Input ownership and transformations

Prefer pure transformations that return replacement values. Report mutation of
caller-owned, shared, or cached inputs when aliases or repeated calls can observe
changed data. Callers should explicitly capture returned replacements. Keep
persistence, network access, time, and randomness at an explicit orchestration
boundary when this makes the transformation easier to reason about and test.
Returning a copy does not make an I/O operation pure.

Copy each changed ancestor before updating nested values. A copied list still
shares its elements; a shallow model copy or object spread still shares nested
objects. Readonly types and frozen fields do not guarantee deep immutability.
Prefer direct map/filter transformations or fresh, unescaped builders; do not
require repeated copying of a growing accumulator.

Allow documented in-place APIs, framework-required mutation, and explicit
stateful owners such as transactions, caches, and clients. Show the ownership
contract and affected alias before reporting a violation; do not infer ownership
from names such as `state`, `draft`, or `request`.

`no-input-model-mutation`, `no-before-validator-input-mutation`, and
`no-unused-copy-result` own their deterministic Python findings. Audit only
additional ownership and effect flows instead of duplicating those diagnostics.
