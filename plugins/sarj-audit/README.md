# Sarj audit plugin

Judgment-layer audits that complement deterministic Sarj lint rules. Commands run read-only unless the user separately requests implementation.

## Commands

| Area | Command |
|---|---|
| Security | `authn-and-authz`, `externalize-configuration-and-secrets` |
| Architecture | `client-server-boundary`, `service-layer`, `data-contracts` |
| Reliability | `error-handling`, `idempotency-and-atomicity`, `concurrency-and-performance`, `observability` |
| Data | `database-schemas-and-migrations` |
| Maintainability | `dead-and-duplicate-code`, `readability-and-naming`, `magic-values`, `libraries` |
| Delivery | `strengthen-ci-cd-and-tooling`, `test-quality-and-strategy` |

Former command topics remain available through focused commands:

- lint coverage, comments, and stepdown ordering are deterministic concerns owned by
  `sarj-standards check`, `doctor`, `show rules`, and `lint-rule-generator`;
- dependency injection is part of `service-layer`;
- explicit attribute validation and Zod modeling are part of `data-contracts`;
- stack detection is shared by every command through the [audit protocol](#audit-protocol); `stack-detection` remains a concise discovery-only command;
- the former broad stack audit is covered by `client-server-boundary`, `service-layer`, and `database-schemas-and-migrations`.

## Skills

- `lint-rule-generator`: design and validate a deterministic rule.
- `promote-lint-rules`: promote clean warning-level rules to errors.
- `ratchet-lint`: fix findings and remove obsolete suppressions safely.

## Audit protocol

Every command follows the same read-only workflow unless the user separately requests implementation.
Domain commands contain only judgment checks. Deterministic checks are centralized in
`sarj-standards`; do not duplicate their findings in an audit report.

### Discover

- Inspect manifests, lockfiles, source roots, generated boundaries, framework configuration, database dialect, and native lint/type/test commands.
- Run deterministic checks first and verify their findings in source.
- Gate checks by the detected stack, including database, runtime, rendering, and tenancy differences.

### Review

Inspect only the selected command's concerns across applicable source roots. Exclude vendored, generated, fixture, snapshot, build, and lock files unless the command explicitly targets them.

### Report

Order findings by severity and confidence. Each finding includes its file and line, evidence and impact, the smallest credible remediation, confidence, and its supporting deterministic rule/tool or `judgment-only`.

Separate confirmed defects from suggestions. Omit speculative, stylistic, duplicate, and unverified tool findings; when no findings remain, state the scopes and checks examined.
