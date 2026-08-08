# Magic values

Audit unexplained literals that obscure policy or units using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).

## Judgment checks

- Repeated values representing limits, timeouts, retry policy, protocol codes, dimensions, units, or business states.
- Boolean and string arguments whose meaning is unclear at the call site.
- UI colors, spacing, or variants bypassing the established design system.
- Deployment-dependent values incorrectly fixed in source.

Do not extract obvious local values such as `0`, `1`, empty collections, conventional indices, or one-off literals whose name would merely restate the value. Prefer typed duration/unit objects and enums when they prevent misuse.
