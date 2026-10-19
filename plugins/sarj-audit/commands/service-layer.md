# Service boundaries and dependency injection

Audit separation of concerns and dependency direction using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol). This command incorporates the former dependency-injection audit.

## Judgment checks

- Handlers or UI components containing business policy, persistence queries, or direct third-party orchestration.
- Services constructing concrete databases, clients, queues, caches, or sibling services rather than receiving dependencies at a composition root.
- Domain logic coupled to framework request/response, ORM, or transport types.
- God services with unrelated responsibilities or pass-through layers that add no policy.
- Scattered persistence or remote-access code without a coherent boundary.

Do not require a class, interface, or service layer for pure functions, trivial CRUD, framework-provided dependencies, or a single stable implementation when added abstraction would not improve testing or substitution.

For an existing decorator or adapter that only forwards a callable's inputs and
result, preserve its input contract with `ParamSpec` or an equally accurate
existing type. Keep intentionally transformed, dynamic, overloaded, reflected,
and async contracts; annotation changes do not prove runtime equivalence.

For an owned, nonmerged TypeScript input port, check that implementations accept
every allowed input. Function-property syntax can enforce contravariance under
`strictFunctionTypes` where method syntax does not. Do not require class arrow
fields or readonly scaffolding, or rewrite merged overloads and receiver contracts.

Establish acquisition and close ownership before changing provider lifetimes.
A request provider borrowing an app-owned resource leaves its single shutdown
close with the application; fresh request-owned resources may close per request.
Keep dependencies alive until their actual consumer finishes. With supported
FastAPI cleanup scopes, a lazy response using the resource needs request-lifetime
cleanup; a body using only materialized values may release it earlier. Do not
force yielded providers or request scope for every stream.

When substituting dependency edges, preserve graph-carried authorization
requirements, enforcement, and generated security schema. The same provider
callable does not make FastAPI `Security` and `Depends` interchangeable. Intentional
empty scopes remain valid; names and cache behavior do not establish authorization.

## Persistence commands

For ordinary model writes, prefer one existing typed `upsert` command that can
express every field the caller is allowed to change. Extend that command at its
owning store when a new ordinary field is added; avoid a separate `set_*` or
`update_*` SQL path per field. Keep immutable identifiers, server-owned values
and privileged fields outside a caller's writable contract. Share implementation
without broadening authorization.

Make the update contract explicit: omitted means leave unchanged, explicit null
means clear when allowed, and a supplied value means replace. A nullable default
or `COALESCE` alone cannot express all three states. Use the established unset
sentinel or fields-set mechanism, preserve existing values on partial writes,
and validate replacement values and cross-field invariants. Do not dump a read
model into an upsert if it exposes fields the caller cannot change.

Prefer an available `upsert_many` for independent model writes. Implement the
bulk method as the canonical database operation and delegate a singleton upsert
with a one-element collection when observable semantics match. A bulk method
that loops over the singleton leaves the repeated database work in place;
reversing both methods' delegation creates recursion. Preserve row conversion,
conflict identity, missing-row behavior, audit fields and caller-visible results.

An upsert can create a missing row. Keep update-only behavior explicit, including
not-found results and required creation fields. Retain specialized operations
when they implement atomic increments, compare-and-swap/version checks, guarded
state transitions, authorization, uniqueness changes, relationship operations,
or a different locking/return contract. They can share lower-level persistence
code without being replaced by an unrestricted model write. Extra method names
alone do not prove redundancy.

`prefer-bulk-upsert`, `store-field-update-reuses-upsert`,
`store-get-delegates-to-bulk-read` and `prefer-psycopg-executemany` own their
deterministic cases. Review additional source-proven contracts and flows here.

## Input ownership and transformations

Prefer pure transformations that return replacement values. Report mutation of
caller-owned, shared, or cached inputs when aliases or repeated calls can observe
changed data. Callers should explicitly capture returned replacements. Keep
persistence, network access, time, and randomness at an explicit orchestration
boundary when this makes the transformation easier to reason about and test.
Returning a copy does not make an I/O operation pure.

Separate value-producing queries and conversions from commands that change
observable state. Consume a returned value; do not call a conversion solely for
validation exceptions and then continue with its original inputs. A validation
command should return `None` (or `void` in TypeScript), while a conversion should
return the checked value its caller uses. Do not hide input mutation, persistence,
network writes, or event publication inside a value-producing transformation.
An exception assertion explicitly observes validation behavior and is valid.

`no-discarded-validation-result` owns source-resolved Python conversions with an
explicit exception branch and a discarded value. Audit additional effect flows
with concrete ownership and call-site evidence. Keep documented stateful owners,
framework contracts, and third-party command/result APIs; require an explicit
effect boundary when application code wraps them in a transformation.

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
