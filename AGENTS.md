# Standards routing

Before editing a rule, state `Routing: <repository>, because <required evidence>`.

- Use `sarj-ai/repo-standards` when a finding depends on the exact tracked Git tree: a
  filename's existence or placement, repository topology or migrations, pull-request size,
  ownership, delivery/GitHub state, or a repository-wide API/document set.
- Use `sarj-ai/code-standards` when a finding depends on source or configuration semantics in
  Python, TypeScript, SQL, Terraform/HCL, Markdown, YAML, JSON, or shell, or changes lint
  engines, presets, baselines, adoption, release, or fleet rollout.
- A path may select a semantic parser. If the path or basename alone is sufficient to emit the
  finding, the rule belongs in `repo-standards`.

Examples: banning a tracked verifier filename belongs in `repo-standards`; rejecting a
Terraform expression that derives access from `var.environment` belongs here.

For rule work, follow `plugins/sarj-skills/skills/lint-rule-generator/SKILL.md`. Run
`make verify` before review.

When this checkout's `verify` target calls `.github/scripts/make-local-check.sh`
and `sarj-local-check` is installed, run `make verify` directly so its phases can
yield shared capacity. Keep the outer supervisor for older checkouts, other
targets, and Git hooks. Verification stops after a failed phase; `make -k` keeps
going within that phase. Later phases reuse the TypeScript build from the
successful first phase.

For release recovery, never retarget an immutable package tag. If publishable
files changed after a tagged version, bump the affected package and exact
sibling pins, then require a separate non-publishable merge with normal
exact-revision CI before reconciliation publishes. Use the rollout controller
only after the version is published, and leave consumer approvals intact.
