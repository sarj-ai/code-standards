---
name: rollout-standards-release
description: Propagates a published Sarj Standards bundle to every registered consumer through the repository's deterministic rollout controller. Use when releasing or merging Standards, propagating or backfilling a Standards version, finishing a lint-rule promotion, repairing a failed consumer upgrade, or checking that all downstream rollout PRs exist and can merge.
---

# Roll out a Standards release

Drive fleet adoption through `make rollout VERSION=<published-version>`. Treat
the repository's typed rollout module and checked-in consumer registry as the source of truth; do not recreate its
clone, update, diff, branch, PR, or auto-merge logic in ad hoc commands.

## Select the operation

- For an audit or status request, run `plan --version VERSION`, then
  `status --version VERSION`. Do not create branches or PRs.
- For an explicitly requested propagation or published release, run
  `plan --version VERSION`, inspect the result, then run
  `apply --version VERSION` and `status --version VERSION`.
- To repair incomplete historical releases, run `reconcile`. Use the reported
  version with `status` before making any nondeterministic change.
- Never run `apply` for an unpublished version. Publishing, merging the source
  release, approving PRs, and bypassing branch protection require separate
  authority.

Run commands from the Standards repository root. Require an exact version; do
not guess from a working tree with uncommitted or unreleased version changes.

## Handle an incomplete rollout

1. Preserve the controller's branch and PR. Rerun `apply` safely before doing
   manual recovery; the operation is idempotent.
2. If a human modified the rollout branch, the base moved incompatibly, or the
   controller rejects the diff, stop and report that condition. Never force
   push, overwrite the branch, broaden the allowed diff, or bypass protections.
3. If consumer CI fails, inspect the failing check and reproduce it on the
   controller-created branch. Edit consumer source only when that PR already
   exists and CI demonstrates that remediation is necessary. Keep the repair
   in the same rollout PR and avoid unrelated changes.
4. Rerun the consumer's configured verification, then rerun `apply` and
   `status` for the exact version.
5. Leave approval-required PRs for an authorized human. Codex must not approve
   its own work or weaken a ruleset; repository auto-merge owns the final merge
   after required checks and approvals pass.

## Completion rule

Do not report a release, rule promotion, or propagation task complete until:

```bash
uv run --project packages/standards --frozen python -m sarj_standards.libs.release.rollout --registry .sarj-standards-rollout.toml status --version VERSION
```

reports every registered consumer as `pr-open`, `merged`, or
`already-current`. Report the exact version, all consumer outcomes, remaining
required approvals or failing checks, and the recovery command when incomplete.
