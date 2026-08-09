---
name: audit-protocol
description: Shared read-only discovery, review, and reporting protocol for every Sarj judgment-layer audit command.
---

# Audit protocol

Every audit command follows this read-only workflow unless the user separately requests implementation. Domain commands contain only judgment checks. Deterministic checks are centralized in `sarj-standards`; do not duplicate their findings in an audit report.

## Discover

- Inspect manifests, lockfiles, source roots, generated boundaries, framework configuration, database dialect, and native lint, type, and test commands.
- Run deterministic checks first and verify their findings in source.
- Gate checks by the detected stack, including database, runtime, rendering, and tenancy differences.

## Review

Inspect only the selected command's concerns across applicable source roots. Exclude vendored, generated, fixture, snapshot, build, and lock files unless the command explicitly targets them.

## Report

Order findings by severity and confidence. Each finding includes its file and line, evidence and impact, the smallest credible remediation, confidence, and its supporting deterministic rule or tool, or `judgment-only`.

Separate confirmed defects from suggestions. Omit speculative, stylistic, duplicate, and unverified tool findings. When no findings remain, state the scopes and checks examined.
