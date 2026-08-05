# Readability and naming

Audit clarity problems not already enforced by deterministic comment or file-ordering rules using the shared [audit protocol](../README.md#audit-protocol).

## Judgment checks

- Vague dumping-ground modules such as `utils`, `helpers`, or `common` that mix unrelated responsibilities.
- Names that describe implementation history rather than current domain meaning.
- Inconsistent vocabulary for the same concept across API, service, and persistence layers.
- Dense expressions, deep nesting, clever control flow, or re-export indirection that materially impedes comprehension.
- Stale explanatory text whose claims conflict with the implementation.

Do not report subjective renames without showing the ambiguity they resolve. Prefer local simplification and established project vocabulary over new naming schemes.
