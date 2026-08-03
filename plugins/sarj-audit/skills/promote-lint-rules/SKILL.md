---
name: promote-lint-rules
description: Promotes clean lint rules from warning to error without introducing failures.
---

# Promote lint rules

Use this skill when the user asks to strengthen existing lint severities.

1. Inventory warning-level rules and scoped suppressions in the repository's effective configuration.
2. Run the exact lint command used by CI, preserving its environment and file scope.
3. Promote only rules with zero findings across their full scope. Change the narrowest relevant configuration and preserve unrelated settings.
4. Rerun the linter and configuration validation. Revert a promotion if it creates errors or changes unrelated behavior.
5. Report promoted rules, retained warnings and their counts, files changed, and verification commands.

Do not remove suppressions, fix violations, commit, or push unless the user separately asks for those actions. Recommend `ratchet-lint` for warning classes that still have findings.
