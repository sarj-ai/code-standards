# Dead and duplicate code

Use the [audit protocol](../skills/audit-protocol/SKILL.md).

Review unused paths beyond native unused-code findings, drifting business-logic
copies and layers without policy, safety or meaningful reuse. Trace reflection,
plugins, framework/generated entry points and public consumers before deletion.
Prefer deletion to speculative abstraction. Dependency substitution belongs in
[libraries](libraries.md).

Knip warnings need complete entry-point configuration and clean resolution;
unsupported workspaces, dynamic config and unresolved imports are inconclusive.
Do not infer application deletion safety from one warning.

For inherited TypeScript config, compare native compiler results with an
in-memory omission. Limit reductions to redundant scalar booleans explicitly
inherited by private leaf configs; preserve options, files, references and
diagnostics. Keep intentional pins/public bases. Arrays and paths require their
own contract evidence, not a hand-written `extends` resolver.
