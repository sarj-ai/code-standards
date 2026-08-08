# Libraries and platform capabilities

Audit hand-rolled code and dependency choices using the shared [audit protocol](../skills/audit-protocol/SKILL.md#audit-protocol).

## Discover by ecosystem

Inspect the detected manifests and lockfiles: `pyproject.toml`/`uv.lock` or requirements files for Python; `package.json` and npm, pnpm, Yarn, or Bun lockfiles for JavaScript; and the equivalent native files for other ecosystems. Use repository-native dependency commands when available. Do not assume npm or install packages during discovery.

## Judgment checks

- Custom parsing, retries, CLI plumbing, validation, serialization, caching, scheduling, cryptography, or protocol code that a maintained library or platform API handles more safely.
- Heavy or abandoned dependencies where the standard library, runtime, framework, or a smaller maintained package provides the needed behavior.
- Legacy APIs when a stable modern API materially improves safety, typing, portability, or code size.
- Multiple dependencies providing the same capability.

For every recommendation, compare maintenance activity, license, security history, runtime/bundle cost, transitive dependencies, migration effort, and net lines removed. Do not recommend churn based only on novelty or download counts.
