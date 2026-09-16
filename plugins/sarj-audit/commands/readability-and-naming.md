# Readability and naming

Audit clarity problems not already enforced by deterministic comment or file-ordering rules using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).

## Judgment checks

- Vague dumping-ground modules such as `utils`, `helpers`, or `common` that mix unrelated responsibilities.
- Names that describe implementation history rather than current domain meaning.
- Inconsistent vocabulary for the same concept across API, service, and persistence layers.
- Dense expressions, deep nesting, clever control flow, or re-export indirection that materially impedes comprehension.
- Stale explanatory text whose claims conflict with the implementation.

Do not report subjective renames without showing the ambiguity they resolve. Prefer local simplification and established project vocabulary over new naming schemes.

## Conditional request construction

When several conditional object spreads obscure which request fields are
present, consider a typed local object followed by conditional assignments.
Show the comprehension problem at the call site; a single clear conditional
spread is not a finding by itself.

Synthetic example:

```ts
// Before
const query = {
  ...(searchText ? { search: searchText } : {}),
  ...(sortOrder ? { sort: sortOrder } : {}),
};

// After: SearchQuery is the existing wire contract.
const query: SearchQuery = {};
if (searchText) {
  query.search = searchText;
}
if (sortOrder) {
  query.sort = sortOrder;
}
```

Preserve the original truthiness or definedness check: replacing `if (limit)`
with `if (limit !== undefined)` starts sending zero. An omitted property differs
from an own property set to `undefined`, especially for patches and defaults.
Preserve assignment order, overwrites, getter evaluation, and readonly
contracts. Do not recommend mutation when the object escapes before construction
finishes or the contract intentionally requires immutable construction.
