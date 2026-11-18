# Data contracts

Apply [protocol](../skills/audit-protocol/SKILL.md).

Show producer, admitted invalid value and failing consumer before strengthening
a contract. Preserve parsed evidence; generic maps/trusted values need no
duplicate parsing. Correlate proven variants without erasing drafts, partial
updates, unknown variants or extension keys. Omission/null/value can differ;
brands, casts, frozen fields and `TypedDict` provide no runtime validation.

At an unvalidated structured-input boundary, prefer a named Pydantic schema in
Python or Zod schema in TypeScript over repeated field reads and handwritten
coercion. Native CLI tokenization can feed that schema. Preserve contractual lazy
fallbacks and coercions; qualify any intentional change to accepted inputs,
unknown fields or error timing. Do not reparse trusted models or replace ordinary
dictionary lookups merely because they use `get`.

Keep composite identities as typed tuples or records in memory. Across a storage,
wire or UI-key boundary, use an unambiguous protocol such as JSON arrays; delimiter
joining needs proven escaping or an enforced delimiter-free domain. Trace every
producer and consumer, including React keys, and check delimiter-containing,
empty and Unicode components for collisions and round-trip loss.

Establish stable configuration invariants when publishing constructed or updated
values as valid for their role and schema version. Trace every admission, write
and mutation path; publish the checked, normalized result. Readers can reuse
established evidence while those guarantees hold. Preserve legitimate drafts,
partial updates, historical representations and error timing. Hydrating untrusted
or differently versioned data remains an admission boundary; current time,
authorization and mutable external state can require checks at use.

Prefer domain types and declarative constraints. Extract cohesive validation
helpers where they clarify ownership or enable reuse, with thin framework
bindings. Preserve validator mode, order, context, evaluation count and object
lifetimes. Method names and line counts do not establish redundant validation
or justify moving it.

Preserve coercions, aliases, defaults, extras, error locations, Python/JSON paths,
fields-set, construction/identity and collection protocols. Pydantic tagged
dispatch precedes variant validators/defaults; boolean literals can admit
integers. TypeScript unions need forbidden members only for required exactness.

Check validator order and mutation: assignment failure need not roll back,
`model_copy(update=...)` skips validation, and revalidation may preserve identity.
For lasting cross-field invariants, validate a complete replacement; round trips
can lose private/excluded state. Trace both predicate branches and generic-result
evidence; preserve genuine narrowing, caller ownership and public/stateful APIs.
