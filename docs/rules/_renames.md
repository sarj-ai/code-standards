# `_renames` — evidence

`src/rules/_renames.ts` holds the old-name -> new-name map and nothing else;
`src/index.ts` reads it and registers each old name as a deprecated alias.

## Renamed in 7.0.0

| Old name | New name | Why |
| --- | --- | --- |
| `jsdoc-restates-signature` | `no-restated-jsdoc` | Its sibling is `no-restated-comment`. The declarative form broke the family's naming, and the new name is shorter and says the same thing. |
| `no-async-callback-in-waitfor` | `no-async-callback-in-wait-for` | `waitFor` kebab-cases to `wait-for`. `eslint-plugin-testing-library` spells it that way in `no-wait-for-multiple-assertions`, `no-wait-for-side-effects` and `no-wait-for-snapshot`. |
| `strict-test-assertions` | `prefer-whole-object-assertion` | The old name described a mood, not a defect, and gave no clue what the rule reports. The rule collapses a run of `expect`s on one receiver into one assertion about the whole object. |
| `trailing-value-narration` | `no-trailing-value-narration` | Every other rule in the comment family is `no-`-prefixed; this one named the defect without saying it was disallowed. |

## Migrating

Every old name stays REGISTERED as a deprecated alias of the same rule object.
A config entry, an `eslint-disable` comment or a suppressions file naming the old
name keeps resolving and keeps reporting; ESLint surfaces the deprecation and
names the replacement through `meta.deprecated.replacedBy`.

Neither preset wires an alias, so nothing double-reports.

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

## Why the old names are not simply dropped

A `SARJ110 -> SARJ083` renumber in the Python package dropped the old code. Every
consumer running a shrink-only baseline gate saw the old key fall to zero and the
new key appear from nothing, and a per-rule shrink-only gate reads an appearing
key as growth — so a pure rename failed CI in repositories that had not changed a
line. Keeping the alias registered means the rename is a two-step migration a
consumer controls: adopt 7.0.0 with the old names still working, rewrite the
names and the baseline in one commit, done.

`tests/rule-docs.test.ts` pins all of it: every old name resolves, every alias
shares the live rule's `create` and `messages`, every alias is deprecated and
names its replacement, the live rule is not itself deprecated, no preset wires an
alias, and neither the shipped `eslint.strict.mjs` nor the README's rule table
still carries an old name.

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
