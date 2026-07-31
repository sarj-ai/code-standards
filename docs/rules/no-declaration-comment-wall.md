# `no-declaration-comment-wall` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-declaration-comment-wall.test.ts);
every guard below has a case asserting it, and the mutation log at the end names
the case that kills each knob. This file holds what a test cannot carry: the
measurements that chose each threshold, the false-positive family each guard
exists to stop, and the ARM THAT WAS MEASURED AND DROPPED.

```ts
export enum OrderStatus {
  /** The order is pending. */
  PENDING = "pending",
  /** The order is completed */
  COMPLETED = "completed",
  /** The order is a draft. */
  DRAFT = "draft",
  /** The order is archived. */
  ARCHIVED = "archived",
}
```

`no-type-member-comment-wall` asks this question of an interface body and a type
literal. It cannot see an enum body or a class body, which is where the other
half of the walls are. Same judgement, same thresholds, same exemption floor —
they live in `_comment-wall.ts` so the two rules cannot drift.

## The predicate

An enum body or class body where at least `minCommentedMembers` (3) members
carry a comment, those members are at least `minCommentedRatio` (0.6) of the
declaration, and at least `minRestatedRatio` (0.75) of those comments add at
most `maxNovelWords` (1) content word beyond the member's own DECLARATION text.
Every threshold is a `meta.schema` option.

## Three guards this rule has and its sibling does not

Each was built after reading a finding it got wrong, and each is scoped to this
rule rather than folded into the shared `carriesValue`: the sibling measured 0
false positives over 46,861 files without them, and on an object TYPE a one-word
comment really is a name restatement that its own group-label guard separates.

**`isLabel` — one content word is a tag, not a re-spelling.** With
`maxNovelWords` at 1, a single novel word scores as a restatement by arithmetic
rather than by meaning. `// dummy` beside `interval: options?.interval || ''`
(grafana `CloudWatchLogsQueryRunner.ts:181`) and `// Mimir` / `// Prometheus`
beside the two spellings of the same query parameter (grafana
`prometheusApi.ts:74`) are the shape: one word that the name cannot say. This is
the same family as the Python class-body attempt's `TargetMode` mapping table,
recorded below.

**`isTagsOnly` — a block of JSDoc tags is a directive.** `/** @ignore */`
carries `ignore`, which is one novel word. `medusa`'s `js-sdk` marks half its
class members that way (`store/index.ts:5`,
`payment/abstract-payment-provider.ts:110`), and every one read as a
restatement without this.

**`declarationRange` — an object or array VALUE is not the member's own words.**
The sibling reads a comment against `sourceCode.getText(member)`, which for a
field initialised to an object literal includes the whole literal. `// Hover
background` over `'&::before': { background: controlItemBgHover }` (ant-design
`splitter/style/index.ts:98`) then has both its words "already said" — by the
value it labels, not by the name it describes. A method body is excluded for the
same reason and always was.

## The arm that was measured and DROPPED

The rule was built with a third arm over `ObjectExpression`, on the theory that
a config object literal is the same shape. **It is not, and it is dropped.**

Over the two corpora below the object-literal arm produced 9 findings against
the enum/class arms' 9. Read at source they were **3 clear true positives**
(supabase `Logs.constants.ts:598`, twenty `gaxios-error-mocks.ts:2`, dub
`rewards.ts:108` — comments that re-spell the key with a space), **1 false
positive** (outline `server/routes/api/comments/schema.ts:92`, a Zod request
schema whose field comments are the published API reference), and **5
arguable** (react-router `entry.ssr.tsx:13` twice, typescript-eslint
`consistent-type-imports.ts:167`, dub `client.ts:15`, dub
`app-sidebar-nav.tsx:126`).

The failure is structural, not a missing guard. An object literal's keys are
frequently a TABLE — routes, mock fixtures, filter options, navigation areas —
and a comment restating a key is the reader's index into a long block rather
than a re-spelling of a declaration. A schema-object exemption was built for the
outline case and then discarded with the arm: fitting a guard to one finding on
the corpus that produced it is not evidence.

At 1 false and 5 arguable out of 9, the arm sits outside the band this repo
holds a deletion rule to. The enum and class arms sit at 0 and 9.

## Measured

Two independent corpora, each swept whole and every finding read against source.

| corpus | repos | files | findings | true | arguable | false |
| --- | --- | --- | --- | --- | --- | --- |
| A | 32 | 112,925 | 4 | 4 | 0 | 0 |
| B | 17 | 42,176 | 5 | 4 | 1 | 0 |

**Corpus A** (ant-design, astro, axios, excalidraw, grafana, immer, immich,
material-ui, medusa, nest, novu, nx, outline, payload, playwright, prisma,
query, react-router, redux-toolkit, refine, storybook, supabase, swr, tldraw,
trpc, twenty, typescript-eslint, ui, umami, vite, vitest, zod):

* `medusa/packages/core/utils/src/order/status.ts:6` — 5 of 6 enum members
  documented `The order is <member>.`
* `medusa/packages/core/js-sdk/src/admin/property-label.ts:5` — 5 of 6 SDK
  methods documented `List property labels`, `Create a new property label`.
* `outline/app/models/Star.ts:9` — 6 of 7 fields documented
  `The document ID that is starred.` beside `documentId`.
* `outline/app/models/Subscription.ts:12` — 7 of 7, same shape.

**Corpus B** (apollo-client, directus, docs, documenso, dub, formbricks, hono,
mobx, n8n, openstatus, puppeteer, rxjs, starlight, type-fest, typeorm, unkey,
zustand):

* `n8n/packages/@n8n/typeorm/src/schema-builder/table/Table.ts:15` — **24 of 31**
  fields documented `Table columns.` beside `columns`.
* `n8n/packages/@n8n/typeorm/src/metadata-builder/EntityMetadataValidator.ts:31`
  — `Validates all given entity metadatas.` beside `validateMany`.
* `n8n/packages/@n8n/typeorm/src/query-builder/RelationIdLoader.ts:12` —
  `Loads relation ids of the given entity or entities.` beside `load`.
* `n8n/packages/testing/playwright/services/variables-api-helper.ts:16` —
  `Create a new variable` beside `createVariable`.
* `n8n/packages/cli/src/workflows/workflow-static-data.service.ts:10` — the one
  ARGUABLE finding: two of the three rows are clean restatements, but
  `/** Saves the static data if it changed */` states a precondition the name
  does not.

**Zero on this repo's own TypeScript source** (122 files).

**Read the volume honestly.** Nine findings over 155,101 files is a fifth of the
density the sibling rule measured (22 over 46,861). This is a rare shape that is
unambiguous when it appears, not a common one — a house adopting it should
expect it to fire on a handful of model and SDK classes and then stay quiet.

## Mutation log

Every guard and every threshold was inverted in turn and the suite re-run. Each
mutant dies:

| mutation | killed by |
| --- | --- |
| drop `isLabel` | the `TargetMode` CLI-tag enum |
| drop `isTagsOnly` | the `@ignore` class |
| drop `carriesValue` | the status-code enum |
| `declarationRange` → the member's full range | the `Theme` nested-value class |
| drop `isGroupLabel` | the `Config` region-label class |
| drop the test / story / generated gates | one case each |
| `options.maxNovelWords` → the literal 1 | the `maxNovelWords: 2` case |
| `minCommentedMembers` 3 → 2 | the two-commented-rows enum |
| `minCommentedRatio` 0.6 → 0.2 | the three-of-eight enum |
| `minRestatedRatio` 0.75 → 0.6 | the one-substantive-in-three enum |

One guard was **removed** rather than kept. The sibling carries a `claimed` set
so a shared comment cannot be counted once per adjacent member; here every
mutation of it left all 19 cases passing, because `documentingComment` already
assigns each comment to at most one member — a leading comment must be alone on
its line and a trailing one must start on the member's last line, and no line
satisfies both. A line that cannot fail is not a guard.
