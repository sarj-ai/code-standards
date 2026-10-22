# Authentication and authorization

Use the [audit protocol](../skills/audit-protocol/SKILL.md).

Trace trusted identity through alternate routes, methods and background entry
points. Verify server-side capabilities and object/tenant scope; request IDs and
client visibility cannot establish authorization. Check token audience, issuer,
rotation, revocation and storage against the actual trust boundary. Inspect
middleware before reporting a missing guard; tenancy checks require tenancy.
