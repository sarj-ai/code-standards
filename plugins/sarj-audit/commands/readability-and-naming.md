# Readability and naming

Audit clarity problems not already enforced by deterministic comment or file-ordering rules using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).

## Judgment checks

- Vague dumping-ground modules such as `utils`, `helpers`, or `common` that mix unrelated responsibilities.
- Names that describe implementation history rather than current domain meaning.
- Inconsistent vocabulary for the same concept across API, service, and persistence layers.
- Dense expressions, deep nesting, clever control flow, or re-export indirection that materially impedes comprehension.
- Stale explanatory text whose claims conflict with the implementation.
- Lint-driven aliases or repeated annotations where an existing typed API or inferred type already expresses the same contract. Prefer supplied callback values over re-reading mutable state; preserve evaluation count, captured snapshots, intentional type contracts, public-library attributes, and framework-required annotations.

Do not report subjective renames without showing the ambiguity they resolve. Prefer local simplification and established project vocabulary over new naming schemes.

The `no-conditional-empty-object-spread` rule owns ternary object spreads with
an empty-object branch. Do not duplicate its diagnostics.
