# Test quality and strategy

Use the shared [test-value skill](../skills/test-value/SKILL.md) on changed tests
or the requested suite, following the [audit protocol](../skills/audit-protocol/SKILL.md).

Run `code-standards observe --test-value` when the installed bundle supports it.
Use `--base <ref>` for changed tests or pass explicit paths. Incomplete analysis
is unavailable evidence, not a clean audit. Existing deterministic findings are
reported once; remaining judgments need a concrete contract and wrong outcome.

Return the location, contract, evidence, smallest useful change, and focused
command. Preserve valid smoke, no-throw, compatibility, and property contracts.
