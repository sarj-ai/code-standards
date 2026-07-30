---
name: lint-rule-generator
description: Defines, validates, documents, versions, and prepares release handoff for deterministic Sarj lint rules and strict configurations across supported toolchains.
---

# Lint Rule Generator

Turn a requested policy into the narrowest deterministic rule that enforces it,
then coordinate every affected Standards package and consumer-facing artifact.

## Workflow

1. **Clarify the policy and scope**
   - Capture violating and compliant examples, intended severity, exclusions, and
     whether existing tools already enforce the policy.
   - Detect which registries apply: Python AST/ruff integration, TypeScript ESLint,
     SQL, IaC, shared configuration, or documentation-only guidance.
   - Do not create equivalent rules in unrelated languages unless their semantics
     and false-positive boundaries genuinely match.

2. **Discover the Standards checkout**
   - Locate the repository from the current working tree or repository metadata;
     never assume an absolute developer path.
   - Read the affected package's registry, neighboring rules, tests, version files,
     generated config sources, release workflows, and contributor guidance before
     editing.

3. **Implement one coherent rule**
   - Choose a stable rule ID and name, and use them consistently in implementation,
     registries, diagnostics, tests, strict configs, and documentation.
   - Add focused positive, negative, boundary, and regression tests. Diagnostics
     must identify an actionable location and remediation without depending on
     repository-specific paths.
   - For config-only policies, update the canonical config source rather than a
     generated consumer copy.

4. **Coordinate packages and generated artifacts**
   - Update every affected Python, TypeScript, SQL, IaC, lint-config, and tsconfig
     package manifest or registry. Leave unaffected packages unchanged.
   - When shared configs change, run `make sync-configs` and then
     `make check-configs-synced`; never hand-edit synced root copies.
   - Keep package metadata and inter-package dependency constraints coherent. Bump
     versions according to the repository's release policy and the compatibility
     impact of the change.
   - Regenerate and validate every affected lockfile after a manifest version or
     dependency changes, including `uv.lock`, `package-lock.json`, and equivalent
     package-manager locks. A manifest-only bump is incomplete.
   - Update release manifests, changelogs, tag/workflow documentation, or publishing
     inputs when required by the package's existing release mechanism. Do not invent
     a parallel release path.

5. **Evaluate real code, then refine**
   - Run the rule against representative source roots in current Sarj
     consumers, including Banking/Noura and Bulbul where the relevant language or
     stack is present.
   - Add external open-source fixtures only when they test a missing ecosystem
     pattern. Record false positives and convert each accepted edge case into a
     regression test.
   - Use audit agents only when explicitly requested; partition by independent
     source root or language and reconcile their findings against the same rule
     contract.

6. **Validate and prepare release handoff**
   - Run focused tests first, followed by the affected package's build, lint, and
     typecheck commands. Run repository-level checks when the change crosses package
     boundaries.
   - Verify generated configs are synchronized, manifests parse, rule IDs are unique,
     documentation links resolve, and searches find no stale rule names or versions.
   - Summarize affected packages, required version bumps/tags, consumer upgrade
     steps, and any intentionally unsupported stacks so the release can be produced
     and adopted without hidden manual work.
   - This workflow prepares a release; it does not publish packages, create or move
     tags, or modify consumer repositories unless the user explicitly authorizes
     those external state changes.
