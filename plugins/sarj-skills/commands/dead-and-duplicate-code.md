# Dead and duplicate code

Apply [protocol](../skills/audit-protocol/SKILL.md).

Before deleting, trace reflection, plugins, generated/framework entry points and
public consumers. Knip warnings require complete entry-point configuration and
clean resolution; unresolved imports or unsupported/dynamic workspaces are
inconclusive. Prefer deletion to speculative abstraction. Dependency replacement
must improve contract fidelity, security/license, maintenance or runtime cost
after migration; inspect manifests, locks and callers without installing.

For inherited TypeScript config, compare native compiler output after in-memory
omission. Reduce only redundant scalar booleans in private leaves; preserve pins,
public bases, files, references and diagnostics. Arrays/paths need separate
equivalence evidence; avoid hand-written inheritance resolution.
