---
name: ratchet-lint
description: Goes through a single repository, fixes lint warnings automatically, removes suppressions/ignores from configuration files, and "ratchets" the codebase.
---

# Ratchet Lint Skill

This skill automatically burns down lint warnings in a repository by fixing them, removing their suppressions, and updating configurations.

## Instructions

When the user asks to ratchet the lint warnings:
1. Run the linters configured in the repository (e.g., `ruff`, `eslint`, `mypy`) to gather warnings.
2. For each file with warnings, use your intelligence or AST autofixers (like `ruff --fix`, `eslint --fix`) to automatically resolve as many issues as possible.
3. If there are remaining warnings, manually review and fix the issues using code editing tools.
4. Once an issue class is fully fixed across the codebase, remove any suppressions/ignores for it from the configuration files (e.g., `pyproject.toml`, `.eslintrc`, `.ruff.toml`).
5. Run the linter again to ensure the codebase remains clean without the suppression.
6. Commit the changes and provide a summary of the issues fixed and suppressions removed.
