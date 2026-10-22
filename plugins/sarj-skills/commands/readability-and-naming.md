# Readability and naming

Use the [audit protocol](../skills/audit-protocol/SKILL.md).

Show ambiguity or material comprehension cost before proposing vocabulary,
responsibility or control-flow changes. Review stale claims and hidden invariants
beyond native comment rules; replace prose with executable parity when possible.
Preserve meaningful snapshots, public annotations and evaluation count.

Simplifications must retain SQL NULL/anti-existence policy, HCL nested replacement
and null clearing, and YAML's decoded command boundaries. Syntax acceptance is
not behavioral equivalence.

React does not await event handlers or catch their async failures in error
boundaries. Trace rejection ownership; a handler already owning feedback needs
no extra synchronous wrapper. Promise-returning props can intentionally transfer
ownership to their caller.
