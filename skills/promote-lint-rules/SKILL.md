---
name: promote-lint-rules
description: Promotes standard rules from "warning" to "error" once a codebase is clean.
---

# Promote Lint Rules Skill

This skill monitors and upgrades linting rules in a codebase. Once the codebase is clean of a specific warning, this skill promotes that rule to an error to prevent regressions.

## Instructions

When the user asks to promote lint rules:
1. Identify any linting rules currently configured as warnings or suppressed in configuration files (e.g., `pyproject.toml`, `.eslintrc`, `.ruff.toml`).
2. Run the linters to verify if there are any violations of these rules currently in the codebase.
3. For any rule that currently has ZERO violations (i.e., the codebase is clean for that rule), promote the rule to an `error`.
    - This involves changing the configuration to treat it as an error or removing the `warn` flag for that specific rule.
4. If a rule has violations but is close to being clean, suggest running the `ratchet-lint` skill first to burn down the remaining issues.
5. Verify the updated configuration by running the linter one last time to ensure no new errors were introduced by the promotion.
6. Commit the changes and provide a summary of the rules promoted.
