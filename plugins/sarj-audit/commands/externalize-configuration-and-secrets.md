# Configuration and secrets

Audit deploy-time configuration and secret handling using the shared [audit protocol](../README.md#audit-protocol).

## Automated baseline

Run secret scanners plus applicable `no-raw-env`, `no-secret-in-log`, `no-repeated-string-literal`, and `prefer-module-level-constant` rules.

## Judgment checks

- Credentials, tokens, private keys, sensitive endpoints, or customer data committed in source, examples, fixtures, logs, or generated artifacts.
- Environment variables read throughout business logic rather than parsed once into a typed configuration boundary.
- Missing startup validation for required settings or unsafe defaults that silently enable insecure behavior.
- Deployment-specific values embedded in code when environments legitimately need different values.

Do not externalize stable language-level constants merely to make them configurable. Never print a suspected secret while reporting it; identify only its location and type.
