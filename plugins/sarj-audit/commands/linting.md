# Linting coverage

Audit gaps in deterministic static analysis using the shared [audit protocol](../README.md#audit-protocol).

## Procedure

- Inventory configured linters, plugins, rule selections, per-file exclusions, suppressions, and CI invocation for each language and file type.
- Compare installed rules with enabled rules using the tool's own configuration/API where possible.
- Run candidate rules against the repository before recommending them. Record finding count, representative true positives, false positives, overlap, and autofix safety.
- Prefer an existing upstream rule, then an existing Sarj rule, before proposing a custom rule.

## Judgment checks

- Valuable installed rules disabled without evidence.
- Source categories omitted from linting or lint commands absent from CI.
- Broad ignores and file-level escape hatches that hide unrelated failures.
- Repeated review findings that are syntactically deterministic enough to encode.

Recommend incremental adoption when a useful rule has existing violations. Do not equate maximal rule count with quality or propose a custom rule without a precise positive and negative corpus.
