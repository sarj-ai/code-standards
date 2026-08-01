# `_retired` — evidence

`src/rules/_retired.ts` holds the withdrawn-name map and nothing else. It is the
single source of truth for names this plugin has shipped and taken away:
`src/index.ts` re-exports it as `retiredRules`, `tests/strict-config-sync.test.ts`
gates it, and consumer-facing migration tooling reads the same map rather than
keeping a second list.

It is the counterpart to `_renames.ts`. A RENAMED rule keeps its old name
registered as a deprecated alias and keeps reporting. A RETIRED rule does not
exist at all: the name resolves to nothing.

## Why a withdrawn name is burned rather than recycled

Consumers carry `eslint-disable-next-line @sarj/<name>` comments and
`eslint-suppressions.json` entries naming rules that no longer exist. A new rule
taking a withdrawn name inherits every one of those suppressions silently — the
comment still parses, still applies, and now silences a judgement nobody wrote it
for.

The failure in the other direction is loud rather than silent, and worse in the
moment. A config naming a rule the installed plugin no longer defines is not a
warning:

```
TypeError: Key "rules": Key "@sarj/ban-loose-type-guards-in-tests": Could not
find "ban-loose-type-guards-in-tests" in plugin "@sarj".
```

ESLint exits 2 and lints nothing, so the whole repo is unlintable until the entry
is deleted. That is why every entry below carries a one-line instruction a
migration script can act on.

## Why the list is derived from git rather than written down

The gate this replaced declared ONE name — `primary-export-file-name` — under a
doc comment claiming it mirrored `sarj-python-lint`'s retired-code set. By then
the plugin had deleted eleven rules across five releases, including all three
removed in #183 and all five removed in 3.0.0. Nothing noticed, because nothing
derived anything: a hand-kept list only fails when a human remembered to edit it,
and the one time that mattered nobody did.

A TypeScript rule's NAME is its filename, so the withdrawn set is recoverable
without anyone writing it down:

```
git log --no-renames --diff-filter=D --name-only HEAD -- packages/typescript/src/rules
```

`tests/strict-config-sync.test.ts` runs exactly that and asserts EXACT set
equality against this map, after subtracting names that are still registered
(a rule file deleted by a RENAME leaves its old name live as a deprecated alias,
so it is not retired). Equality in both directions means a deletion that forgets
an entry fails, and so does an entry invented for a rule that was never deleted.

`--no-renames` is deliberate. Renaming a rule file retires the old name exactly as
deleting it does; rename detection would hide that, and `_renames.ts` is what
distinguishes the two cases.

Both CI lanes check out with `fetch-depth: 0`. A shallow clone has no history to
derive from, and the gate asserts the repository is not shallow rather than
skipping quietly.

## Withdrawn names

| Name | Removed in | Why, and what to do |
| --- | --- | --- |
| `ban-loose-type-guards-in-tests` | 5.0.0 | Read at 39 findings with 0 true positives in the #183 corpus audit. It also shipped in `configs.strict` at `error` with no test file for its entire life. Delete the entry. |
| `no-implicit-attribute-access` | 5.0.0 | Read at 50 findings with 0 true positives in the #183 corpus audit. Delete the entry. |
| `no-sequential-await` | 3.0.0 | 218 findings, 100% range-contained in core `no-await-in-loop`, which the shipped config already enables. Delete the entry. |
| `no-template-literal-in-log` | 2.3.1 | Withdrawn. Delete the entry. |
| `no-unsafe-cast` | 3.0.0 | 1,089 findings, matching `@typescript-eslint/consistent-type-assertions` (`"never"`) at the identical line and column with zero residue. Delete the entry and keep that rule enabled. |
| `prefer-setup-file-mocks` | 5.0.0 | Read at 50 findings with 0 true positives in the #183 corpus audit. Delete the entry. |
| `prefer-shadcn` | 3.0.0 | 645 findings, a subset of `react/forbid-elements`; its 24-position residue was entirely design-system primitives being told not to be the design system. Delete the entry. |
| `primary-export-file-name` | 4.0.0 | 316 findings over 1,966 files; a sample of 30 read 11 harmful / 15 useless / 4 valuable, including telling `next.config.ts` to become `next-config.ts`, which breaks the Next build. Delete the entry. |
| `require-parameterized-tests` | 4.0.0 | Landed in #153 and never wired up: absent from the `rules` record, from every preset and from `eslint.strict.mjs`. Nothing to migrate. |
| `require-schema-validate-search` | 3.0.0 | 14 findings, all matched line-and-column by `@typescript-eslint/consistent-type-assertions`. Delete the entry. |
| `single-public-export` | 3.0.0 | 3 findings, all also reported by the then-live `primary-export-file-name`, itself withdrawn in 4.0.0. Delete the entry. |

## The Python twin

`packages/python/tests/code_ledger.json` does the same job for `SARJ###` codes,
where the identifier is a number rather than a name and reuse is therefore
easier. It records every code ever allocated or reserved against the rule that
held it, is append-only, and is gated the same three ways: a new rule with no
ledger line fails, a rule claiming a code the ledger records for someone else
fails, and the deleted-module walk over git history fails if the ledger is
missing a code that once shipped.
