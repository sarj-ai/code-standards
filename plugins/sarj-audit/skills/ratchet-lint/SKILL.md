---
name: ratchet-lint
description: Safely burns down one repository's lint findings and tightens only obsolete suppressions.
---

# Ratchet lint

Use this skill when the user asks to fix existing lint findings or reduce suppressions.

1. Identify the repository's effective lint configuration and run the same commands and scopes used by CI.
2. Group findings by rule and risk. Apply tool-provided safe fixes first, then review their diff before making focused manual fixes.
3. Preserve behavior. Do not silence findings, weaken rules, or perform broad rewrites merely to reduce the count.
4. Remove a suppression only after its complete scope is clean and the suppression is no longer needed. Keep intentional exceptions narrow and documented.
5. Rerun formatting, linting, type checks, and relevant tests after each coherent batch.
6. Report fixes, remaining findings, suppressions removed or retained, and verification commands.

Do not commit, push, publish, or change unrelated rule severities unless the user separately requests it.
