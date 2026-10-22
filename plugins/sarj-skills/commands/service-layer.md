# Service boundaries and dependency injection

Use the [audit protocol](../skills/audit-protocol/SKILL.md).

Review policy/persistence leakage and dependency direction beyond native service
rules. Add boundaries only when substitution or coherent policy warrants them;
pure functions and simple CRUD need no ceremonial layers.

Establish resource acquisition/close ownership and the last consumer's lifetime,
including lazy responses. Preserve FastAPI authorization edges and security
schema when substituting providers; `Security` and `Depends` can differ despite
the same callable.

Consolidate ordinary writes through compatible existing commands without widening
writable fields or access. Trace accepted fields through validation, INSERT and
conflict assignments; preserve omitted/null semantics and update-only behavior.
Bulk reads/writes must retain per-key authorization, ordering, results and atomic
increments/transitions. Native store rules own proven delegation patterns.

Show an observable alias/effect before reporting input mutation or a discarded
conversion. Copy changed ancestors, not growing accumulators; shallow copies
retain nested aliases. Preserve documented stateful owners and framework APIs.
