# Authentication and authorization

Audit authentication and authorization defects using the shared [audit protocol](../README.md#audit-protocol).

## Judgment checks

- Protected routes without authentication, including alternate methods and background entry points.
- Object access not scoped to the authenticated owner or tenant. Infer identity from trusted server context, never request-controlled subject or tenant IDs.
- Privileged operations without server-side role or capability checks; client-side visibility is not authorization.
- Tokens without suitable expiration, audience, issuer, rotation, revocation, or secure storage.
- Spoofable identity signals, unsafe secret comparison, and sensitive authentication data in logs or URLs.

Only apply tenant checks when the system is multi-tenant. Trace middleware and framework-level guards before reporting a missing local check.
