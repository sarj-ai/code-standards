---
name: lint-rule-generator
description: Designs and validates deterministic lint rules from concrete anti-patterns.
---

# Lint rule generator

Use this skill when the user asks to create or refine a lint rule.

1. Obtain a precise bad pattern, why it is harmful, applicable languages, exclusions, and examples that must not match.
2. Search the existing upstream and Sarj rule catalogs. Prefer configuration or extension of an existing rule over new code.
3. Choose only the implementations needed for the affected languages; do not create both Python and TypeScript variants without evidence.
4. Build a minimal positive/negative test corpus before implementation. Include near misses, framework idioms, generated code, aliases, nesting, and fixes where applicable.
5. Implement the narrowest deterministic syntax or semantic check that covers the corpus. Do not encode naming guesses or architectural judgment as a lint error.
6. Run unit tests, formatter, linter, type checks, and the rule against representative local repositories when available. Inspect every match or a documented sample large enough to estimate false positives.
7. Refine until the corpus passes and observed false positives are acceptably low. Document limitations, safe autofix behavior, and examples.

Do not clone unrelated public repositories, install dependencies, edit external repositories, commit, or publish unless the user separately authorizes those actions.
