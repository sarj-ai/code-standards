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
the focused tests for the change before review; CI owns the full suites. `make verify`
and `Native make verify` are optional diagnostics, not merge gates.

To merge, rebase onto current main, bump each changed package past main's version
with exact sibling pins (two bumps merged back to back can claim one version, as
#2143 and #2150 did), regenerate generated files, and push. Squash-merge with
`--admin` once the required checks pass. If a later rebase changed only versions or
generated files, merge once `release-ready` passes. Release refuses a main revision
whose CI failed, so fix a red main forward.

For release recovery, never retarget an immutable package tag. If publishable
files changed after a tagged version, bump the affected package and exact
sibling pins, then require a separate non-publishable merge with normal
exact-revision CI before reconciliation publishes. Use the rollout controller
only after the version is published, and leave consumer approvals intact.
