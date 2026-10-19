# Test quality and strategy

Use the shared [test-value skill](../skills/test-value/SKILL.md) on changed tests
or the requested suite, following the [audit protocol](../skills/audit-protocol/SKILL.md).

Run `code-standards observe --test-value` when the installed bundle supports it.
Use `--base <ref>` for changed tests or pass explicit paths. Incomplete analysis
is unavailable evidence, not a clean audit. Existing deterministic findings are
reported once; remaining judgments need a concrete contract and wrong outcome.

Return the location, contract, evidence, smallest useful change, and focused
command. Preserve valid smoke, no-throw, compatibility, and property contracts.

Vitest's upstream `valid-expect` and `no-focused-tests` checks start as warnings
in Vitest files. A bare `expect(value)` needs a matcher; the optional assertion
message remains valid. Focused tests receive editor feedback before execution,
while Vitest's CI guard remains authoritative at runtime. Assertion promises
belong to typed `no-floating-promises`. The syntax-only async check is excluded
because it reports stored assertions even when they are awaited later. Bun and
Playwright retain their own rules.
