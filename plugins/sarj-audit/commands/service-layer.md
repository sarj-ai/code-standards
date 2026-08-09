# Service boundaries and dependency injection

Audit separation of concerns and dependency direction using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol). This command incorporates the former dependency-injection audit.

## Judgment checks

- Handlers or UI components containing business policy, persistence queries, or direct third-party orchestration.
- Services constructing concrete databases, clients, queues, caches, or sibling services rather than receiving dependencies at a composition root.
- Domain logic coupled to framework request/response, ORM, or transport types.
- God services with unrelated responsibilities or pass-through layers that add no policy.
- Scattered persistence or remote-access code without a coherent boundary.

Do not require a class, interface, or service layer for pure functions, trivial CRUD, framework-provided dependencies, or a single stable implementation when added abstraction would not improve testing or substitution.
