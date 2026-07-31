# `_comment-wall` — evidence

The comment-VOLUME judgement, shared by
[`no-type-member-comment-wall`](no-type-member-comment-wall.md) (interface bodies
and type literals) and
[`no-declaration-comment-wall`](no-declaration-comment-wall.md) (enum bodies and
class bodies).

Both rules ask the same question of different node kinds: **is this run of member
comments a wall of restatement, or documentation?** The exemption floor and the
"adds no new word" test have to be identical across the two or the family
contradicts itself — a comment the object-type rule spares and the class rule
deletes is a rule set that cannot be explained to the person whose writing is
being deleted. So the judgement lives here and neither rule owns a copy.

## What is shared

| export | what it decides |
| --- | --- |
| `WALL_DEFAULTS`, `WALL_SCHEMA` | the four thresholds, and the `meta.schema` both rules expose for them |
| `carriesValue` | the exemption floor — a comment carrying a ticket, a URL, a unit, a digit, a documented default, a quoted example, a value-bearing JSDoc tag, a banner or non-ASCII prose |
| `WALL_STOPWORDS`, `novelWords`, `knownTokens` | the "adds no new word" test |
| `BARE_LABEL_RE`, `labelStems`, `commentBody` | reading a comment as a label |
| `isWall` | the three-threshold verdict |

Each threshold's rationale is in
[`no-type-member-comment-wall.md`](no-type-member-comment-wall.md), which is where
they were first measured.

## What is deliberately NOT shared

`isLabel` and `isTagsOnly` live here but are called by
`no-declaration-comment-wall` only.

`no-type-member-comment-wall` measured zero false positives over 46,861 files
without them, and on an object TYPE a one-content-word comment really is a name
restatement — `// links` over `links: LinkDescriptor[]` — which that rule's own
group-label guard already separates by asking whether the word names something
*other* than the member below it.

The populations the sibling reads are different. An enum body and a class body
spell mapping tables and generator directives with exactly one content word
(`// Mimir` beside one of two spellings of a query parameter, `/** @ignore */`
above half an SDK's members), and with `maxNovelWords` at one those score as
restatements by arithmetic rather than by meaning. Folding the two guards into
`carriesValue` would change a shipped rule's verdicts without re-measuring it, so
they are scoped to the rule that measured them.

`declarationRange` is shared but only the sibling calls it; the object-type rule
reads `sourceCode.getText(member)`, which for a type member has no body and no
initializer to exclude.

## The one behavioural difference between the two rules

`no-type-member-comment-wall` carries a `claimed` set so a shared comment cannot
be counted once per adjacent member. `no-declaration-comment-wall` does not, and
the reason is recorded in its evidence file: every mutation of that line left the
whole suite passing, because `documentingComment` already assigns each comment to
at most one member. A line that cannot fail is not a guard.
