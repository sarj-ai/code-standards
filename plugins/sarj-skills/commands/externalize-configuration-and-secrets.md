# Configuration and secrets

Use the [audit protocol](../skills/audit-protocol/SKILL.md).

Beyond native secret/configuration checks, trace startup validation, insecure
fallback behavior and deploy-specific values fixed in business logic. Keep one
typed configuration boundary; externalize only values that legitimately vary.
Stable language constants need no setting. Report suspected secrets by location
and type, never by value.
