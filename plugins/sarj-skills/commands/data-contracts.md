# Data contracts

Apply [protocol](../skills/audit-protocol/SKILL.md).

Show producer, admitted invalid value and failing consumer before strengthening
a contract. Preserve parsed evidence; generic maps/trusted values need no
duplicate parsing. Correlate proven variants without erasing drafts, partial
updates, unknown variants or extension keys. Omission/null/value can differ;
brands, casts, frozen fields and `TypedDict` provide no runtime validation.

Preserve coercions, aliases, defaults, extras, error locations, Python/JSON paths,
fields-set, construction/identity and collection protocols. Pydantic tagged
dispatch precedes variant validators/defaults; boolean literals can admit
integers. TypeScript unions need forbidden members only for required exactness.

Check validator order and mutation: assignment failure need not roll back,
`model_copy(update=...)` skips validation, and revalidation may preserve identity.
For lasting cross-field invariants, validate a complete replacement; round trips
can lose private/excluded state. Trace both predicate branches and generic-result
evidence; preserve genuine narrowing, caller ownership and public/stateful APIs.
