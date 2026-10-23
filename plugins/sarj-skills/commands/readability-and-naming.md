# Readability and naming

Apply [protocol](../skills/audit-protocol/SKILL.md).

Require demonstrated ambiguity or comprehension cost. Replace stale prose/hidden
invariants with executable parity where useful; preserve snapshots, public
annotations and evaluation count.

Simplifications must preserve SQL NULL/anti-existence, HCL nested replacement/null
clearing and decoded YAML command boundaries.

React neither awaits event handlers nor sends their async failures to error
boundaries. Trace rejection ownership; existing feedback needs no extra wrapper,
and promise-returning props may transfer ownership.
