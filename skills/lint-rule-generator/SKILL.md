---
name: lint-rule-generator
description: Automates the process of defining and refining new lint rules from natural language descriptions.
---

# Lint Rule Generator

This skill automates the process of defining a new lint rule, from natural language description to a refined, deterministic rule evaluated against real-world codebases.

## Instructions

When invoked to create a new lint rule, follow this workflow:

1. **Accept Input**:
   - Ask the user for a natural language description of the issue or anti-pattern they want to prevent.

2. **Draft the Rules**:
   - Create a deterministic Python AST rule and a TypeScript ESLint rule targeting the described anti-pattern.
   - Save these rules into the `standards` repository located at `/Users/nasrmaswood/code/standards`.

3. **Evaluate Against Codebases**:
   - Run the newly created lint rules against the following repositories to gather matches and evaluate false positives:
     - `noura-be`
     - `bulbul`
     - 10 top open-source TypeScript and Python repositories.

4. **Analyze and Refine using `codex exec`**:
   - Integrate and invoke `codex exec` in your workflow to analyze the execution results and lint errors.
   - Feed the lint outputs into `codex exec` using the best model available to evaluate false positives.
   - Iterate on the rule implementations in the `standards` repository based on Codex's analysis to refine the logic and eliminate false positives.
