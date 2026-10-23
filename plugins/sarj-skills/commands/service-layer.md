# Service boundaries

Apply [protocol](../skills/audit-protocol/SKILL.md).

Move privileged client work/presentation policy to an authorized boundary only
when contracts or measured cost improve. Add layers for real substitution/policy,
not simple CRUD. Keep deploy-varying settings at a typed startup boundary; inspect
unsafe fallbacks without turning stable constants into settings.

Trace acquisition/close ownership through the last consumer, including lazy
responses. FastAPI provider changes must preserve authorization/security schema:
`Security` and `Depends` can differ for the same callable.

Reuse compatible write commands without widening fields/access. Preserve
omitted/null, update-only, per-key authorization, ordering, results and atomic
transitions. Require observable alias/effect evidence for mutation/discarded-copy
findings; copy changed ancestors, preserve intentional stateful APIs.
