# `_renames` — evidence

`src/rules/_renames.ts` holds the old-name -> new-name map and nothing else.
`scripts/sync-rule-ledger.py` reads it and writes one `renamed` row per entry into
the shipped `rule-ledger.json`, which is what `sarj-lint-configs doctor` prints.

## Renamed in 7.0.0, aliases deleted in 9.0.0

| Old name | New name | Why |
| --- | --- | --- |
| `jsdoc-restates-signature` | `no-restated-jsdoc` | Its sibling is `no-restated-comment`. The declarative form broke the family's naming, and the new name is shorter and says the same thing. |
| `no-async-callback-in-waitfor` | `no-async-callback-in-wait-for` | `waitFor` kebab-cases to `wait-for`. `eslint-plugin-testing-library` spells it that way in `no-wait-for-multiple-assertions`, `no-wait-for-side-effects` and `no-wait-for-snapshot`. |
| `strict-test-assertions` | `prefer-whole-object-assertion` | The old name described a mood, not a defect, and gave no clue what the rule reports. The rule collapses a run of `expect`s on one receiver into one assertion about the whole object. |
| `trailing-value-narration` | `no-trailing-value-narration` | Every other rule in the comment family is `no-`-prefixed; this one named the defect without saying it was disallowed. |

## Migrating

7.0.0 kept every old name REGISTERED as a deprecated alias of the same rule
object. 9.0.0 deletes the aliases: the new names are the only names.

So on 9.0.0 an old name in a config, an `eslint-disable` comment or a suppressions
baseline is not a deprecation warning — it is `Could not find "@sarj/<rule>" in
plugin "@sarj"`, ESLint exits 2, and no file in the repo is linted. Run
`sarj-lint-configs doctor` BEFORE upgrading; it names every file holding an old
name and the name to write instead. Then:

```bash
# In a consumer repo: config files, disable comments and suppression baselines.
for pair in \
  jsdoc-restates-signature:no-restated-jsdoc \
  no-async-callback-in-waitfor:no-async-callback-in-wait-for \
  strict-test-assertions:prefer-whole-object-assertion \
  trailing-value-narration:no-trailing-value-narration
do
  old="${pair%%:*}"; new="${pair##*:}"
  git grep -lz "@sarj/$old" -- ':!*.lock' | xargs -0 -r sed -i '' "s|@sarj/$old|@sarj/$new|g"
done
```

The map is also exported, so a codemod can read it instead of copying it:

```js
import { renamedRules } from "@sarj/eslint-plugin";
```

## Why the aliases went

The alias was a migration window, not a permanent second name. Held open, it is a
name whose only definition is "the other name", carried in the published plugin
and in every test that has to prove the two stay identical — and a consumer
reading `plugin.rules` counts four entries that are not rules.

What the window was actually protecting against is a name that stops resolving
with nothing anywhere saying where it went. That protection now lives in
`rule-ledger.json`, which is stronger than the alias was: the alias only helped a
repo that had already upgraded and was already failing, while `doctor` reads the
ledger BEFORE the upgrade and names every stale reference and its replacement. It
also covers the removals an alias cannot — the ESLint rules dropped in 5.0.0, the
`SARJ110 -> SARJ083` renumber, a retired pre-commit hook id.

That renumber is the failure worth keeping in mind. It dropped the old code
outright; every consumer running a per-rule shrink-only baseline gate saw the old
key fall to zero and the new key appear from nothing, which such a gate reads as
growth — so a pure rename failed CI in repositories that had not changed a line.
The fix for that is one commit rewriting the names and the baseline together,
which is exactly what `doctor` output tells a consumer to write.

`tests/rule-docs.test.ts` pins it: a frozen list, itself pinned at 51 entries, of
the names 6.1.0 shipped — each of which must be a live rule, a recorded rename or
a recorded retirement, so an ACCIDENTAL disappearance still fails while these four
intentional ones pass. Then: no old name registered, every rename target live and
not itself deprecated, no name in both `_renames.ts` and `_retired.ts`, no old
name in either preset, and neither the shipped `eslint.strict.mjs` nor the
README's rule table still carrying an old name.

`tests/rule-ledger.test.ts` and `packages/lint-configs/tests/test_rule_ledger.py`
pin the other half: the ledger records exactly the renames the plugin declares, a
`renamed` row may only name a rule that no longer resolves, and `doctor` prints
the replacement for each.

`tests/strict-config-sync.test.ts` derives the withdrawn set from git history and
demands set equality with `_retired.ts`. It excuses a deleted rule FILE only when
`_renames.ts` records where the name went — reading the rename map rather than
inferring it from a registered alias, which is what the alias used to supply. The
two maps are held disjoint, so the exclusion cannot launder a real withdrawal.

## What left `eslint.strict.mjs`

The `@sarj` block used to carry per-rule measurement comments duplicated from the
rule modules, plus two section banners (`2.8.0 / 2.9.0 additions`, and
`anti-comment-verbosity family (2026-07)`) of the kind `no-comment-cruft` reports.
It also carried a written list of "deviations from the plugin's strict tiers"
that had outlived every deviation it described — `strict-config-sync.test.ts`
asserts tier parity on every run, and its `DECLARED_DEVIATIONS` map is empty. The
block is now the rule keys and nothing else: 1,116 lines down to 1,047. Each
rule's measurements live in `docs/rules/<rule>.md`, which its `meta.docs.url`
points at.
