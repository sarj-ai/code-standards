# `no-comment-cruft` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-comment-cruft.test.ts).
This file holds what a test cannot carry: the measurements that chose each
threshold, the false-positive family each guard exists to stop, and the
alternatives that were rejected.

Flag comment cruft — commented-out code, section banners,
leading file-header comment preambles, and redundant narration. Code carries
the *what*; comments are reserved for the *why*. JSDoc (`/** ... */`) is
never flagged, and directive comments (`eslint-`, `@ts-`, `prettier-`,
`biome-`, `c8`, `<reference`, `TODO`, `FIXME`) are ignored.

Repeated statement walkthroughs are reported once as a comment wall. A block
must contain at least four simple statements; at least three comments must
weakly narrate their directly aligned statement; comments must cover 60% of
the block and 75% of attached comments must be weak. A URL/ticket, directive,
constraint, causal explanation, invariant, security note, upstream quirk, or
longer prose comment is never wall evidence. The diagnostic tells an agent to
name operations in code and retain only rationale or constraints, instead of
emitting four variations of “comment narrates the code.”

`redundantNarration` covers three shapes: step markers ("First, …", "Step 2:"),
self-admitted meta-commentary ("for now", "temporary hack"), and a comment
that restates the statement directly below it (`// increment the counter`
above `counter += 1`). The third shape is heavily guarded — see
`restatesNextLine` — because the first attempt at it (PR #98) corroborated by
substring and produced 933 hits at a ~60% false-positive rate. Measured on
7,159 local TS/TSX files: 42 hits, 2 of them wrong (a comment heading a block
whose first statement happened to carry every word), and ZERO hits in the
maintained repos — it is a preventive ratchet with no migration cost.

`fileHeaderPreamble` requires the preamble to contain NO prose sentence. The
original "4+ consecutive `//` lines before the first code" test penalised
syntax rather than content: on a real 42k-LOC codebase, 11 of 15 hits were the
repo's BEST documentation — module headers explaining a stateless idempotency
substrate, one citing RFC 9562 §5.7 — which is precisely the "brief doc
comment for the why" this rule's own message asks for. Exactly one hit was
genuine (an ASCII banner, already covered by `sectionBanner`). What survives
is the content-free preamble: a stack of bare labels/fragments with nothing
explained. A prose header should be a JSDoc block for tooling reasons, but
that is a formatting preference, not cruft, and this rule does not litigate it.

A 2026-07 sweep of 2,186 real TypeScript files (zod, TanStack Query,
react-router, swr, zustand) produced 821 hits and turned up four false-positive
classes, each now guarded at the point that produced it — see
`DIAGRAM_ARROW_RE` (ASCII timelines read as banners), `ENUMERATED_ITEM_RE` (a
numbered walkthrough read as a content-free preamble), `isInsideCommentRun` (a
phrase inside a prose paragraph read as a one-line narration label), and
`hasIllustrationLeadInAbove` (a code sample read as commented-out code because
its `Example:` heading was more than one line up). The bulk of the remaining
hits are real: zod alone carries hundreds of lines of genuinely commented-out
code (e.g. zod/packages/zod/src/v4/core/checks.ts:1231-1244, a whole disabled
`$ZodCheckTrim` implementation), and those still fire.

A 2026-07 corpus run of the SHIPPED rule turned up two live false positives,
both fixed here: `REGION_RE` matched the bare word `region`, so prose opening
with it read as a folding marker (six sites, e.g. `// Region centroids for
map_pan.`), and `for now` fired on a ticket-bearing scoping note — a comment
naming where the decision is recorded is doing the one thing code cannot, so
protected-class signal S1 now exempts narration at RUN granularity. The same
pass added `sarj-noqa` to `DIRECTIVE_RE` (this repo's own suppression syntax
was missing, so a suppression comment could itself be flagged) and four
detectors that are all ZERO-hit on the flagship first-party repo, the one
that runs this rule at
`error`: bare section labels, the `Helper function to …` opener, `Let's
<verb>`, Unicode box-drawing banners, and an ISOLATED numbered/`Phase N:`
marker. JSX-expression comments stay categorically exempt: `{/* Step 1:
Select Patient */}` mirrors the literal step labels a wizard renders.

A 2026-07 audit re-ran the shipped rule over 25,508 deduped TS/TSX files (six
first-party repos plus zod, trpc, dub, openstatus, formbricks, documenso,
unkey, midday, papermark, cal.com, hono): 4,148 findings — sectionBanner
1,436, commentedOutCode 1,278, redundantNarration 894, untrackedTodo 538,
fileHeaderPreamble 2 — of which 59 were read at random, stratified by message
id, at a ~9% false-positive rate. The banner and dead-code detectors held up
(9/9 and 8/9 true positives on independent second samples) and are untouched.
All three FP classes sat in `redundantNarration` or in one branch of
`looksLikeCode`, and each is now guarded at the point that produced it:

  1. `restatesWholeStatement` — the `DUMMY_TRANSLATION_RE` branch reported a
     short `get`/`set`/`return` comment on the LEXICAL match alone, with no
     reference to the code beneath it, in a rule whose whole narration design
     is "total corroboration or nothing". 402 lexical candidates corpus-wide,
     340 of them corroborated by nothing at all — that is where the class
     lived (`// Set initial value` above `handleChange();`,
     papermark/lib/hooks/use-breakpoint.ts:21, where the comment is the only
     thing saying why the handler runs eagerly; `// Get access token` above
     `const urlParams = new URLSearchParams({`, dub/apps/web/app/(ee)/api/
     partners/platforms/callback/route.ts:97, heading the whole token
     exchange). Recall cost, stated plainly: the 62 corroborated hits stay and
     the 340 uncorroborated ones go, of which roughly half were genuine block
     labels worth deleting. It trades ~170 weak true positives for ~170 false
     positives and makes the branch obey the contract the file documents.
  2. `JUSTIFICATION_RE` now guards the step-narration branch as well as the
     meta-commentary one, and knows the bare-pronoun connectives.
  3. `TYPE_MEMBER_CONTAINERS` — a call-shaped comment inside an interface body
     or type literal is a label for the overload below it, not commented-out
     code, because the statement it resembles could not have parsed there.

NOT changed, deliberately: 1,128 findings (27%) sit within two lines of a
same-message sibling, because a three-line ASCII box is two `sectionBanner`
reports and a three-line TODO is three `untrackedTodo` reports. Collapsing a
contiguous `//` run to one report would cut the headline count ~25% without
removing one false positive — it changes report granularity, not precision,
and would make a reporting change indistinguishable from a precision win in
exactly the number this audit is measured by. Per-line reporting is also
deliberate: each line of a commented-out block is separately deletable, which
is why the test suite pins two reports for a two-line block.

## The `sectionBanner` arm reaches JSDoc (2026-07)

A JSDoc block used to be exempt from this rule wholesale — `isJsDoc(comment)`
short-circuited before every check. That exemption is right for the thing it was
protecting (a JSDoc block is where the "why" conventionally lives) and wrong for
one shape: a block whose ENTIRE body is a signpost.

    /**
     * REMOVE METHODS
     */
    override remove(entities: T[], options?: RemoveOptions) { … }

That is the same section banner the rule already names in `//` form, wearing the
one comment syntax nothing measured. The doc-diet ratchet
(`tests/rule-docs.test.ts`) says the same thing about this repo's own source:
"none of this plugin's own comment rules could see it — `no-comment-cruft` and
friends exempt JSDoc, so the one place in the repo where prose grew without
limit was the one place nothing measured."

**Measured.** 80 candidate blocks over four OSS corpora (medusa, twenty, nest,
typescript-eslint; 37,208 files), **80 of 80 true positives, 0 false**; the
protected-class guard below then withholds one, so the shipped rule reports 79.
They are
`/** * STATE */`, `/** * MUTATIONS */`, `/** * HOOKS */`, `/** CART START */` /
`/** CART END */` bracket pairs around type members, and a full ladder of
`/** * FIND METHODS */` … `/** * PRIVATE METHODS */` down one repository class.
Zero findings on the four first-party repos (4,054 files) and zero on this
repo's own source: first-party spells its banners with `//`, which this rule
already caught 2,796 times.

### The three conditions, and the family each stops

- **EVERY content line must be a signpost.** One shouted line above a paragraph
  of prose is a heading for documentation the reader came for, not a signpost.
- **Not protected-class prose.** A shouted line that carries a
  protected-class signal is a warning someone chose to shout —
  `/** DOES NOT RETRY */` — and stays. This also spares `/** DEPRECATED … */`,
  which is a value tag; that is the one candidate of the 80 it withholds.
- **A shouted label is two to four ALL-CAPS words.** One word is an acronym
  carrying the fact the name cannot (`/** UTC */`, `/** ISO */`) and is spared;
  five or more is a sentence someone shouted. Digits are excluded for the same
  reason — `ISO 8601` is a citation, not a heading. Lowercase is excluded
  outright: `/** the retry budget */` describes the member below it.

A trailing JSDoc is left alone, as everywhere else in this rule: it annotates
the code beside it rather than heading a region.

## Evidence relocated from the source

### `REGION_TITLE_MAX_WORDS`

`={4,}` not `={3,}`: `===` is TS strict-equality and appears in prose comments.
`[\u2500-\u257f]` is the Unicode box-drawing block — `────────` is the same
section separator as `--------`, and 34 of them were sitting in the corpus
under a check that only knew ASCII.

### `if`

A VS Code / Visual Studio folding marker: `//#region`, `// region helpers`,
`// endregion`. The title must be short and unpunctuated. Matching the bare
word alone flagged running prose that merely opens with it — six sites across
the corpus, the clearest being a first-party matching pipeline whose comment
reads "region, sector AND facility_type are HARD constraints when the
investor names them — …", plus its five TypeScript siblings. A marker *names* a region; a sentence discusses
one, and a sentence has punctuation (a full stop included — `// Region
centroids for map_pan.` is prose) and more than a handful of words.

### `"schemas", "selectors", "setters", "setup", "state", "styles`

A bare one-word signpost naming a region of the file (`// Types`, `// Main`,
`// Helpers`). It is a table of contents for a file that should have been
split, and it goes stale silently. 22 corpus hits, 12 of 12 sampled were true
positives. Closed vocabulary on purpose: a one-word comment outside this list
is far more likely to be a genuine label for a value.

### `// Gated on the narration verb list because the third-person`

"Helper function to check if a path is active" — the opener announces the
*category* of the thing below (which its declaration already states) and then
restates its name. 6 corpus hits, 6 true positives.

### `// (which has no code-tail) is not mistaken for commented-ou`

An ASCII sequence-diagram arrow. A long rule of dashes that ENDS IN AN ARROW
HEAD is drawing a timeline, not separating sections: `req------->res` is the
clearest documentation of a race condition anyone has written, and deleting it
loses information no function extraction can recover. Measured on 2,186 real
TypeScript files (zod / TanStack Query / react-router / swr / zustand): 8 of
the 83 section-banner hits were one such diagram, swr/src/index/use-swr.ts:524
through :549, explaining request/mutation interleaving. A real banner
(`// ---------- Checks ----------`,
react-router/scripts/pr.ts:157) has no arrow head and still fires.

### `/**`

--- "restates the next line" ---------------------------------------------
A comment that opens with a narration verb and whose every remaining content
word already names what the statement below it computes says nothing the code
does not (`// increment the counter` / `counter += 1`). Three guards keep the
inference sound, because *coincidental* token overlap is the failure mode that
sank the first attempt at this shape (PR #98: `service` matching
`locationService` gave a ~60% false-positive rate):

 1. Total corroboration — one unmatched word (`// guard the race from
    PLT-812`) means the comment carries something the code does not, so it
    stays.
 2. The comment must sit on top of a single-line, value-producing *statement*.
    A comment above a block, a declaration, a type member or an object-literal
    entry (`// store state` above `interface SessionState {`) labels a region
    of code; the words it shares with the first line of that region are
    incidental.
 3. Only the head of the statement counts — everything up to the first `(` —
    so the comment must restate what the statement *computes* (its target and
    its callee), not merely something it passes as an argument.

### `/**`

A causal connective. `for now` inside a sentence that also states WHY is a
justification, not an admission — `// Needed for now since router.fetch is not
async until v7` (react-router/.../__tests__/router/lazy-discovery-test.ts:2412,
and :2505) is the reason the sleep exists, which is exactly what the rule wants
a comment to carry. A bare `// quick fix for now` still fires.

The 2026-07 corpus audit (25,508 deduped TS/TSX files, 894 narration findings
of which 73 were step markers and 39 meta commentary) found the escape wired
into the META_COMMENTARY_RE branch only, so a step marker that stated its own
reason was flagged anyway — the branch and the rationale it is supposed to
respect never met. Both branches now share the escape.

The list also missed the bare-pronoun forms of the connective it already knew:
dub/apps/web/lib/actions/partners/update-discount.ts:68 reads "we only cache
default group pages for now so we need to invalidate them", and `so that` was
in the list while `so we` was not. Recall cost: a bare `// First, do X` and a
bare `// quick fix for now` still fire, because neither states a reason.

### `statementBelow`

WHY the wider form here: this shape is already pinned down to a <=4-word
comment opening with `get`/`set`/`return`/`increment`, and for that shape an
argument IS the object of the verb. Measured over the 2026-07 corpus, the
`DUMMY_TRANSLATION_RE` branch had 402 lexical candidates: head-only
corroboration keeps 40 of them, whole-statement corroboration keeps 62, and
all 22 of the difference are unambiguous restatements — `// Set mobile
viewport` above `await page.setViewportSize(MOBILE_VIEWPORT)` (documenso, 4
sites), `// Return hex digest` above `return hmac.digest("hex")`
(papermark/lib/utils/generate-checksum.ts:11), `// Get current session token`
above `const currentToken = await getCookie(UNKEY_SESSION_COOKIE)` (unkey).
Head-only would have thrown all 22 away for nothing.

### `if`

`standalone` is false when the comment is one line of a contiguous `//` block.
The step and meta shapes are single-line tells; inside a paragraph they match a
clause of running prose rather than a label. Measured on 2,186 real TypeScript
files (zod / TanStack Query / react-router / swr / zustand), 9 of 42 narration
hits were exactly that — e.g. react-router/integration/bug-report-test.ts:26
("First, make sure to install dependencies and build React Router. From the
root of / the project, run this:"), a six-line contributor instruction, and
react-router/packages/react-router/lib/dom/ssr/routes.tsx:663. A restatement of
the next line is still checked in a block, since it is corroborated against the
code rather than against a phrase.

### `* True when the comment at `index` belongs to a contiguous ``

Measured on the 2026-07 corpus (25,508 deduped TS/TSX files): 76 of the 4,148
findings (1.8% of the rule, 5.9% of `commentedOutCode`) were this shape, and
60 of them sat in ONE file — `hono/src/types.ts`, where each `// app.get(path,
handler x5)` names the call signature directly below it. That made a single
pattern the rule's second-noisiest file corpus-wide.

### `if`

A scoping note puts its owner at the end — one first-party four-line canary
comment ends
"EN-only for now — add an AR variant once AR audio exists (PROJ-249)" — so
judging the last line alone read "for now" as an unowned admission. A comment
that names where the decision is recorded is doing the one thing code cannot.

### `}`

True when a prose lead-in (`// Example:`, `// For example:`, a grammar
production head) appears earlier in the SAME contiguous `//` block. The
existing check only looked at the immediately preceding comment, so a code
illustration more than one line below its own heading was read as
commented-out code — measured at
react-router/packages/react-router/lib/hooks.tsx:791, where `// function
Blog() {` sits nine lines under its `// Example:` heading inside one 17-line
block (2 hits there of the 695 commented-out-code hits over 2,186 files).

### `return`

Same for a numbered/bulleted walkthrough. The single corpus hit for this
message across 2,186 real TypeScript files was
react-router/scripts/release-comments.ts:1, a six-step description of
what the script does ("1. get all tags sorted by creation date", …) —
documentation, not a stack of content-free labels.


## `for now` is not self-admitted meta-commentary (2026-07-31 sweep)

`for now` was an alternative inside `META_COMMENTARY_RE`, so the phrase alone
made a comment "self-admitted meta-commentary". Every other alternative in that
regex NAMES the debt — "is a hack", "keeping it simple", "could be refactored",
"not sure if", "quick fix", "temporary workaround". `for now` names nothing; it
is an ordinary temporal qualifier that appears inside genuine scope and
rationale comments.

Measured over **175,852 content-deduplicated `.ts/.tsx/.js/.jsx` files** from
four first-party repos and 61 OSS repos, build output excluded: the phrase drove
**134** of the rule's 2,179 `redundantNarration` findings. Fourteen were read at
source:

| verdict | n | example (verbatim corpus line) |
| --- | --- | --- |
| false positive | 6 | `// our svg icons break if we use data urls, so disable inline assets for now` |
| | | `// skipping utils for now, as it has independent release process` |
| | | `// We don't need the recipient here for now, but if we want to push feed notifications to a specific user we could add it.` |
| | | `// [Joshen] Default to false for now, only used for SQL editor to dynamically invalidate` |
| | | `// Hero only for now; the release feed lands below it as its port arrives.` |
| | | `// This is the only hard-coded actor type, as API keys have special handling for now.` |
| arguable | 6 | `// We only allow DELETE requests for now` (a scope statement) |
| true positive | 2 | `// Empty for now.`, `// Mock data for now - in real implementation …` |

`JUSTIFICATION_RE` rescued none of them: its connective list is narrow, and
`as`, `so <verb>` and `intentionally` are not on it.

`isBareDeferral` replaces the alternative. It fires only when the comment
carries at most **2** content words besides the phrase — deferral with no
substance. Applied to the same 134 findings it keeps **14** and drops **120**.
The 14 kept are, in full: five `Empty for now.`, two `Not needed for now`,
`Internal for now`, `for now client only`, `Nothing to rollback for now`, three
`login manually for now`, and `only track panels for now` — every one of them a
deferral that says nothing about what or why. The threshold is 2 rather than 1
so that `login manually for now` and `only track panels for now` stay flagged;
raising it to 9 re-admits four of the false positives above, which is what the
mutation test in `no-comment-cruft.test.ts` pins.

Cost of the guard: two-word scope statements such as `// Mock data for now` lose
their report. Recorded rather than tuned away — the alternative is 120 wrong
reports on comments that are doing exactly what the rule asks for.

## Rules that were measured and left alone

The same sweep sized the other `redundantNarration` shapes so they are not
re-litigated. Of 2,179 findings: 1,325 restatement (corroborated against the
code below, the heavily guarded path), 228 step-narration, 224 the
`Helper function to …` opener, 172 the remaining meta-commentary, 167 dummy
translation, 52 enumeration, 9 `Let's …`.

The `Helper function to …` opener was read at 14 findings: 8 true positives, 5
arguable, 1 false positive
(`// Helper type exports - infer directly from schemas for Zod v4 compatibility`,
where the opener is followed by a real *why*). At ~7% it is inside tolerance, so
it is left uncorroborated. It is the one shape in `isRedundantNarration` that
consults neither `JUSTIFICATION_RE` nor the statement below, and that is where a
future guard belongs if the class grows.
