# `no-type-member-comment-wall` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-type-member-comment-wall.test.ts);
every guard below has a case asserting it, and the mutation log at the end
names the case that kills each knob. This file holds what a test cannot carry:
the measurements that chose each threshold, and the false-positive family each
guard exists to stop.

```ts
interface SapCredentials {
  // Database host.
  host?: string;
  // Database host port.
  port?: number;
  // Database username.
  username?: string;
  // Database password.
  password?: string;
}
```

`no-restated-jsdoc` already deletes `// Database host.` — every word is
covered by the member. It cannot touch `// Database host port.`, which survives
on one extra word. Correct for one line, wrong for the wall: the reader pays for
the block, not for any single row of it. So the unit of judgement is the TYPE,
and the per-comment test is deliberately looser than a single-comment rule could
justify, because it is the repetition being reported.

**The predicate.** An interface body or type literal where at least
`minCommentedMembers` (3) members carry a comment, those members are at least
`minCommentedRatio` (0.6) of the type, and at least `minRestatedRatio` (0.75) of
those comments add at most `maxNovelWords` (1) content word beyond the member's
own source text. Every threshold is a `meta.schema` option.

## Why the thresholds

Comment density on object-type members is strongly bimodal across 12 OSS
TypeScript repos (7,340 object types with 2+ members): 79% carry no member
comments at all, 8.6% comment EVERY member, 12.4% sit in between. "How many
members are commented" therefore carries almost no signal, which is why
`minCommentedMembers` is only a floor and `minRestatedRatio` / `maxNovelWords`
do the work.

`maxNovelWords` defaults to 1 because two words is exactly enough room for a
definition. Loosening it to 2 takes the OSS corpus from **22 findings to 85**
and admits `name?: string; // Partial match` beside
`slug?: string; // Exact match` — the matching MODE is the one thing neither the
name nor `string` can state — and metrics rows that define their measure
(`views: number; // unique opportunity views`). The option is exposed for a team
that wants the recall; the default does not take it, because this rule deletes
human writing and one wrong deletion is silent.

## Measured

Corpus: **33 OSS TypeScript repos, 46,861 files** (airflow, apollo-client,
cal.com, core, date-fns, documenso, dub, formbricks, hono, immer, litellm,
midday, mobx, nest, nuxt, openstatus, papermark, playwright, prefect, puppeteer,
query, react-router, rxjs, storybook, swr, trpc, type-fest, typeorm, unkey,
vite, zod, zulip, zustand).

| | findings | read | true | false |
|---|---|---|---|---|
| first version (PR #180 as opened) | 28 | 28 | 22 | **6 (21%)** |
| after the guards below | **22** | 22 | **22** | **0** |

The first version was measured over 12 of these repos and reported 8 findings,
8 true, 0 false. That number was an artefact of the smaller corpus: on the full
33 it fires 28 times and **six of those are false**. Every one of the six is now
exempt, and no true positive was lost — the finding set after the fix is the
28 minus exactly those six.

**The six false positives, and the guard each bought**

1. `react-router/packages/react-router/lib/types/route-module-annotations.ts:212`
   — 13 of 14 comments are REGION LABELS: `// links` heads `LinkDescriptors` and
   `LinksFunction`, `// meta` heads three members, and `// default (Component)`
   over `ComponentProps` names the route module's `default` EXPORT. The rule
   documents this exemption and leaked on it, because `minCommentedRatio` only
   catches a label whose run is long and here most runs are one member.
   → the **group-label** guard: a comment is a label when it is ONE bare
   identifier word, names something other than the member below it, and shows
   region evidence (it heads a run only the first member of which is commented,
   or a blank line sets it off). A label documents a region, so it is not
   counted as a member comment at all.
2. `typeorm/src/metadata-args/TransactionEntityMetadataArgs.ts:4` —
   `readonly target: Function` documented "Target class on which decorator is
   used", `readonly index: number` documented "Index of the parameter on which
   decorator is used". Both carry a fact the signature cannot: *which kind* of
   thing the target is, *which kind* of thing the index counts. They scored as
   restatements only because `class` and `parameter` were STOPWORDS.
   → `class`, `method`, `function`, `component`, `hook`, `parameter` and
   `argument` came out of the list. The tag words `param` and `arg` stay: they
   are block punctuation, not prose. (Keeping `param` is what preserves the
   eight cal.com findings, whose JSDoc is a bare `@param name` with no text.)
3. `nest/packages/microservices/external/mqtt-options.interface.ts:116` — a
   vendored copy of the MQTT.js typings, `@see https://github.com/mqttjs/MQTT.js/`
   at the top of the file. Editing its prose desynchronises the copy.
   → `external/`, `vendor/`, `vendored/`, `third-party/` and `third_party/`
   joined `generated/` in `isGeneratedFile`. Python's `_paths.is_generated_path`
   has always held `vendor` / `vendored`; this is the TS side catching up.
4. `storybook/code/renderers/react/src/componentManifest/__testfixtures__/ForwardRef.tsx:3`
   — a docgen-extractor FIXTURE whose three prop comments are the input under
   test; `componentMetaExtractor.qa.test.ts:448` asserts their exact strings.
   `isTestFile` matched `fixtures/` but not `__testfixtures__/`.
   → `__fixtures__/` and `__testfixtures__/` added to `isTestFile`.
5. `storybook/code/renderers/vue3/template/stories_vue3-vite-default-ts/component-meta/reference-type-props/my-props.ts:31`
   and 6. `storybook/test-storybooks/mcp/stories/other/card/Card.tsx:4` — demo
   components in story trees. Prop JSDoc there is not commentary but OUTPUT:
   docgen renders it as the args-table description the reader of the storybook
   sees, and in `my-props.ts` it is also the expected value of a component-meta
   test.
   → `isStoryFile` now matches a `stories/` directory (and Storybook's
   `stories_<framework>/` spelling), not only a `*.stories.*` basename, and this
   rule consults it.

**The 22 that remain, all read.** cal.com ×8 (four repository/port interfaces
whose method JSDoc is the method name in prose plus a bare `@param`, four
`QueueXWebhookParams` types that are `/** Team ID */ teamId?: number` rows),
typeorm ×3 (`JoinColumnOptions.ts:4`, `SapDataSourceOptions.ts:8`,
`CordovaDataSourceOptions.ts:6` — "Database type." on `type`), storybook
`manager-api/modules/shortcuts.ts:35` (12 of 12, "Returns the current
shortcuts." on `getShortcutKeys`), prefect
`ui-v2/src/components/runs/use-runs-saved-filters.ts:93` (8 of 10, "Handler for
deleting a filter" on `onDeleteFilter`), nuxt `vite/src/plugins/vite-node.ts:56`
(5 of 5), hono `src/context.ts:237`, nest
`common/interfaces/features/arguments-host.interface.ts:25` ("Returns the data
object." on `getData()`), query `lit-query/src/createInfiniteQueryController.ts:51`,
midday ×2 (`queue-config.ts:28`, `scheduler-config.ts:52`), litellm
`mcp_tools/types.tsx:273`, date-fns `pkgs/docs/src/types.ts:38`, playwright
`playwright-core/src/tools/mcp/protocol.ts:48`.

Two of the 22 are borderline rather than flat: date-fns's `ReflectionBase` has
one dead row ("The kind string." on `kind: Kind`) and two that each carry a
single real word ("The **module** reflection.", "**Overridden** category."), and
playwright's `ExtensionCommandV2` repeats each key's upstream `chrome.*` call
signature above a member that already spells the same parameters. Both sit
exactly on the `maxNovelWords: 1` line by design. Neither is a comment whose
deletion loses a fact.

## Never flagged

- **Generated, vendored, test, fixture and story files.** Not a nicety: over ten
  first-party repos the raw predicate found 407 walls and **321 (79%) were
  OpenAPI codegen output** — one `types.gen.ts` per repo, every field carrying
  its own title. Editing those is work the next generator run reverts.
- **A member comment carrying a JSDoc value tag** (`@deprecated`, `@see`,
  `@example`, `@internal`, `@alpha`, …) **or a prose default** (`default: true`,
  `defaults to …`). The default of an optional field is the one fact its type
  cannot hold; `vite/packages/plugin-legacy/src/types.ts:1` is eight
  `// default: …` rows.
- **A comment containing a digit, a unit word, a quoted example, `e.g.`, a
  banner rule, or a non-ASCII letter.** Each is a bound, a base, an enumerated
  value or prose the tokenizer cannot read. `// 0..100 (% of width)`,
  `// The 1-based column number.` and `// "sukuk"` were false positives until
  this guard existed.
- **Computed members.** `[resultType]?: ResultType` has no readable name to
  re-spell; redux-toolkit's `// phantom type` ×3 was the last false positive
  this removed.
- **The nine-signal protected class** from `_comments`, as everywhere in this
  family — an exemption floor, never a test.

## The three position guards, and an honest note on them

`documentingComment` requires (a) the member to start its own line, (b) a
leading comment to be alone on its line, and (c) a trailing comment to sit after
the member; `check` additionally claims each comment for at most one member.
Mutating each of (a), (c) and the claim set in turn and re-running the 46,861-file
corpus changes **no verdict at all** — the four guards overlap, and on real
source the claim set alone is enough. They are kept because the shape they
exclude is real (a one-line inline props type under a component's own JSDoc,
which was the entire first-party finding set before any of them existed), and
each is now pinned by a case that fails when the guard is removed. (b) is the
only one of the four that changes corpus behaviour.

## Mutation log

Every knob was mutated and the suite re-run. Before this revision, 15 of 26
mutants survived — including `maxNovelWords: 1 → 99`, which broke nothing at
all, and three "valid" cases that passed for a reason other than the guard they
named (the informative-comments case was saved by the word "secret" matching
the protected class's security signal, the value-tag case by a backtick hitting
the quoted-example regex, and the `// default:` case by `minRestatedRatio`).
Those cases were rewritten to isolate one guard each. All 26 mutants are now
killed:

`maxNovelWords` 1→99 and 1→0 · `minCommentedMembers` 3→2 ·
`minCommentedRatio` 0.6→0 · `minRestatedRatio` 0.75→0.1 · own-line check ·
leading-comment standalone check · trailing-comment position check · claim set ·
`isTestFile` gate · `isGeneratedFile` gate (whole, and the vendored directories
alone) · `isStoryFile` gate (whole, and the `stories/` directory alone) ·
`__testfixtures__` alone · `isProtected` · `VALUE_TAG_RE` · `DEFAULT_RE` ·
`DIGIT_RE` · `UNIT_WORD_RE` · `EXAMPLE_RE` · `BANNER_RE` · non-ASCII ·
computed-member filter · group label (whole, its own-name test, its region
evidence, its bare-word shape) · the STOPWORDS trim.

## Considered and rejected

Three neighbouring shapes were measured and dropped; the numbers are what
killed them.

- **Long paragraph comments** (a `#` block of ≥N lines, Python): **639**
  findings at ≥6 lines over 8 OSS repos, 246 at ≥8, 117 at ≥10. 35 were read;
  **33 were the best comments in the file** — `trio/src/trio/_unix_pipes.py:21`
  on why closure sets `.fd = -1` rather than a flag,
  `django/django/db/backends/base/schema.py:1070`'s index truth table. Length is
  anti-correlated with worthlessness. ~94% FP.
- **Comment density in a region** (≥75% of a function's statements carrying a
  leading comment): 230 findings at 3 statements. 21 read, **16 false** — the
  shape is dominated by attribute-purpose blocks in `__init__` and dense
  algorithm walkthroughs. The 5 true positives were short verb-led step labels
  in tests, each already reachable one at a time by `no-comment-cruft`. ~76% FP.
- **Prose that dwarfs the code** (docstring ≥10 lines and ≥2× the body):
  **1,830** findings. 20 sampled, every one a published API docstring with
  `Args:`/`Example:` over a delegating body. The ratio measures "is this a
  public entry point", not "is this over-documented". ~100% FP.
- **A Python twin of this rule** (class bodies with annotated fields): **1**
  finding over 15 OSS repos, 0 first-party. Python documents fields with
  docstrings and `Field(description=…)`, which SARJ050 / 084 / 085 / 086 already
  cover.
