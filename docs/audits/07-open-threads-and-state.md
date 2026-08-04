# Open threads and exact repo state

Date: 2026-08-03. Read this before starting anything — it records state that is
not recoverable from git history alone.

## Documentation location

These audit records now live under `docs/audits/`. The location is intentionally
restricted to maintain the repository's Markdown convention while preserving
audits that must survive beyond a local handoff directory.

## Two traps in the standards checkout

1. **`~/code/standards` has ~602 staged, uncommitted files.** This is real
   in-flight work (a `docs/rules/` evidence system with 141 files, a
   `scripts/sync-rule-ledger.py`, an untracked `foo`). Working tree matches the
   index. **Never `git reset` or `git checkout .` there.** Do standards work in
   a worktree off `origin/main`.
2. **`main` and that snapshot disagree about the repo's own rules.** `main` has
   **no `docs/` directory** and its committed `CLAUDE.md` never mentions
   `docs/rules`. The rule-evidence system *and* the CLAUDE.md text describing it
   ("`docs/rules/<name>.md` is the only record of what was measured and why")
   exist only in the uncommitted snapshot. Anyone reading CLAUDE.md from the
   working tree is reading uncommitted policy.

Also: `.git/config` had `bare = true` set, which made every git command in the
checkout fail with "must be run in a work tree". Fixed 2026-08-03. If that error
reappears, check `core.bare` first.

## Restored worktrees — all 8 branches intact, need PRs

The worktree directories were deleted at some point on 2026-08-03 (cause
unknown; `git worktree add` prunes registry entries but never deletes
directories, so that was not it). **No commits were lost** — every branch was
verified at its recorded SHA and all have been re-checked-out under `/tmp/wt-*`.

The one unrecoverable loss: `feat/comment-noise-devex` had 4 uncommitted
modified files that existed only in the deleted directory.

| Branch | Commits | Size vs main |
|---|---|---|
| `feat/comment-prose-budget` | 6 | 279 files |
| `codex/org-frontend-correctness` | 1 | 274 files |
| `refactor/sql-self-documenting` | 2 | 227 files |
| `refactor/python-src-self-documenting` | 4 | 188 files |
| `fix/sarj069-subject-shadow` | 1 | 32 files |
| `fix/self-lint-sarj043` | 1 | 32 files |
| `feat/comment-noise-devex` | 1 | 603 files |
| `fix/sarj070-dogfood` | 0 ahead | — |

**Warning:** the four large branches overlap heavily with the 602-file staged
snapshot in the main checkout. Opening them blind will produce conflicting PRs.
Reconcile against that snapshot first and decide what supersedes what.

## Remaining briefs

- **`01-per-rule-adversarial-cleanup.md` — IN PROGRESS.** ~13 of 151 rules done
  (PRs #244–#257). Resume at **SARJ070 `prefer-or-pattern`**: 11 self-findings,
  all classified true positives, but **7 diagnostic previews truncate mid-syntax
  and render invalid Python**. Fix preview rendering before applying any
  rewrite. Branch `fix/sarj070-dogfood` exists.
- **`02-nominal-id-validation.md` — NOT STARTED.** SARJ093 shipped in #218; the
  validation pass never ran. Needs re-calibration against current mains with
  pinned SHAs, then separate consumer migration PRs.
- **`03-hypermodern-python-api-rule-research.md` — COMPLETE.** See
  `05-hypermodern-api-research-findings.md`. Conclusion: ship no new rule.
- **`04-downstream-standards-upgrades.md` — COMPLETE.** All six repos on 0.42.
- **`06-config-authority-and-rule-conflicts.md` — CONFIG AUTHORITY IMPLEMENTED;
  exhaustive pair audit remains open.**

## Shipped 2026-08-03

Standards 0.42 reached all six consumer repositories. Follow-up fixes froze a
frontend burndown clock at mount, mutation-tested `REBASELINE_RULE_IDS`, removed
the docstring deadlock, and restored `D417` after proving it was not a conflict.

## Environment gotchas

- Consumer D's pre-push hook runs the full `make check` CI mirror and needs
  `mise exec node@26.5.1 -- git push`.
- Consumer C's demo lint fully lints any demo **not** in
  `.ci/lint-exempt.json` at `--max-warnings 0`, so comment warnings are fatal.
- Consumer B's stray-virtualenv guard scanned `.git/`, where lefthook creates
  its own venv, failing every local push once hooks had run.
- taplo 0.7.0 **panics** (`assertion failed: entry.comment.is_none()`) on a
  trailing same-line comment when `reorder_keys` must move that entry. The crash
  was read as a non-verdict, so a consumer `pyproject.toml` silently escaped
  its format gate entirely. Fixed by moving the comment to its own line.
- Never run `sarj-standards init --force` in an established repo — it replaces
  repo-owned hooks. Use `sync`.
