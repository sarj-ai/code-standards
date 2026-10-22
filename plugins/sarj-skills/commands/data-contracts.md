# Data contracts

Use the [audit protocol](../skills/audit-protocol/SKILL.md). Deterministic parsing,
record, widening, union, predicate and validator rules own their proven cases.

For remaining flows, show the producer, an admitted invalid value and the failing
consumer. Preserve parsed domain evidence instead of repeatedly rediscovering it;
use the owned schema at untrusted boundaries, precise types internally. Dynamic
maps, generic infrastructure and trusted values do not require duplicate parsing.

Model proven alternatives as complete correlated variants; distinguish roles,
units and state transitions only where substitution breaks a real invariant.
Keep legitimate drafts, partial updates, unknown variants, extension keys and
partial-success states. Omission, null and supplied values can differ. Brands,
casts, frozen fields and `TypedDict` do not validate runtime values.

Migration compatibility includes accepted/coerced input, aliases, defaults,
extra fields, error locations, Python/JSON paths, fields-set behavior and public
construction/identity protocols. Pydantic tagged dispatch precedes variant
validators/defaults; boolean literal equality can admit integers. Structural
TypeScript unions need explicit forbidden members only when exactness is required.
Preserve mixed versus homogeneous collections and dictionary/tuple operations.

Validate the final established value, including validator order and mutable
updates. Pydantic construction validation does not guarantee assignment rollback;
`model_copy(update=...)` skips validation and instance revalidation can return the
same object. Use a complete validated replacement when cross-field invariants
must always hold; serialization round trips can lose excluded/private state.

Trace both branches of predicates and the evidence behind generic results.
Retain genuine narrowing at external/plugin boundaries. Show lost information or
observable incompatible mutation before proposing a stronger contract; preserve
caller-owned input, public overrides and intentional stateful APIs.
