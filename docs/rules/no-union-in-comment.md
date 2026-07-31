# `no-union-in-comment` — evidence

Behaviour is specified by
[the tests](../../packages/typescript/tests/rules/no-union-in-comment.test.ts).
This file holds what a test cannot carry: the measurements, the false-positive
family each guard exists to stop, and the arms that were rejected.

## The shape

A field is declared `string`, and the set of values it actually accepts is
written down beside it — in a comment.

    status: text("status").notNull().default("pending"), // 'pending' | 'in_review' | 'approved' | 'rejected'
    metric: string;                                      // 'attractiveness' | 'financial' | 'locational'

The author already knows the type. They wrote it out, member by member, in
union syntax. What they did not do is put it where the compiler can read it, so
every one of these fields still accepts `"aproved"`, `"IN_REVIEW"` and `""`.
The comment is not documentation of the type; it is the type, misfiled.

This is the cleanest case in the whole comment-hygiene family, because the fix
deletes the comment AND closes a hole in the same edit:

    status: text("status").$type<"pending" | "in_review" | "approved" | "rejected">()

## Why the trigger is the comment, not the name

`prefer-string-literal-union` already flags a `string` field whose NAME looks
like a choice (`status`, `kind`, `role`) — but only when a sibling member of
the same declaration is already a string-literal union, because the name alone
is a guess. This rule needs no guess: the author enumerated the set. A comment
that is nothing but a list of quoted literals is a claim about the closed set
of values, made by the person who knows.

The two rules are kept apart for that reason. One infers a closed set from a
name and needs corroboration; this one reads a closed set the author stated.

## Measured

Sixteen corpora, 68,000+ files, linted through a `cwd`-scoped `Linter` with a
must-fire positive control per repo and hard asserts on both the fatal count and
the "no matching configuration" count (see the harness note below).

| corpus | files | findings |
| --- | --- | --- |
| four first-party repos | 4,054 | 67, over 10 files in 8 apps |
| 17 OSS TypeScript repos | ~68,000 | 2, both in one file |

**Precision: 27 of 27 read at source were true positives, 0 false.** The
first-party sample was 25 drawn with a seeded shuffle; the OSS population was
two, so both were read. The first-party findings concentrate in three
near-identical Drizzle schema modules (20 each) plus seven `lib/types.ts`
modules with one apiece; the OSS findings are two sibling members of one
`userContent.ts` type, `time_period?: string // "0m", "1m", "5m", "1h", …`.

Low volume outside first-party is the expected result and not a defect: the
population is "somebody wrote a union in a comment", and most repos that know
the union write it as a union. The rule is worth its keep because every hit is
both a deletable comment and a live type hole, and because it cannot fire on
anything else.

## The guards, and the false-positive family each one stops

Each is inverted in turn by a mutation run; the case that kills it is named.

| guard | the family it stops | killed by |
| --- | --- | --- |
| the body regex is anchored `^…$` | a sentence that happens to quote two values — `set to 'aa' unless the caller passed 'bb'`, `prefer 'aa', 'bb' is what the legacy importer writes`. The sentence, not the list, is what carries the meaning. | the two prose valid cases |
| the separator is required (`+`, not `*`) | a single quoted value is an EXAMPLE, not a closed set | `// 'aa'` |
| literals cap at 28 characters | quoted SENTENCES — error messages, format strings, prompts | `// 'the requested resource was not found' \| 'the upstream call timed out'` |
| the target must be a bare `string` | a member that already has the union, and a `number`/named-type member for which a string-literal union is not the fix | `kind: 'aa' \| 'bb'`, `kind: number`, `kind: Kind` |
| `string[]` and `string \| null` count | recall: both are still unconstrained strings | the two invalid cases |
| the object-literal path needs a named string COLUMN BUILDER | an arbitrary object value the rule cannot type — `kind: pick()`, `kind: integer('kind')` | those two valid cases |
| the declaration must not already spell every literal | a column that carries the union through `$type<…>()` and a comment restating it — a restatement, which is a different defect | `text('kind').$type<'aa' \| 'bb'>()` |
| a leading comment must sit on the line directly above | a comment separated by a blank line heads a REGION, not a member | the blank-line valid case |
| the trailing anchor steps back over `,` / `;` | recall, and the reason this is a guard at all: a member's own separator belongs to the CONTAINER, so resolving it lands on the object literal and the member is never reached — the bug that hid 60 of the 67 first-party findings on the first run | the `pgTable` invalid case |
| generated files are skipped | output mirrors its generator; nobody edits it | the `@generated` valid case |

## Guards deleted rather than kept

Three guards were written, survived their mutants, and were deleted instead of
being given a test — the same disposition #191 used:

- a `DIRECTIVE_RE` skip, and
- a `hasExternalReference` (protected-class signal S1) skip. Both are subsumed
  by the `^…$` anchor: a directive prefix or a ticket id in front of the list
  means the body is no longer *only* a list. Their valid cases are kept, now
  testing the anchor.
- a "trailing comment must follow its declaration" position check. The anchor
  token is by construction inside the node the walk finds, so a found target can
  never start after the comment. Unreachable.

## Arms rejected on measurement

**A numeric-RANGE arm** — `pct: number; // 0-100`, `confidence: number; // 0..1`
— was written, measured and dropped. 76 findings on the first-party corpus, 4
on OSS; a seeded sample of 20 read at source produced 0 clear false positives
and **20 of 20 arguable**. A range is a UNIT fact, and `no-trailing-value-narration`
already takes the position that the unit is "the one thing the code does not
say, and the reason the fix is a *name*, not a deletion". The only fix inside
the type system is a branded type, which is a far larger ask than deleting a
comment. Rejected on the same bar that rejected the object-literal arm of the
comment-wall rule.

**Unquoted lists** — `// one of: draft, sent, paid` — are not matched. Without
quotes the shape is indistinguishable from ordinary prose with commas, and the
anchor is the only thing keeping this rule at zero false positives.

## Harness note

The measurement above was produced by a `Linter` constructed with
`cwd` set to each repo root and a config ARRAY carrying `files`. Both are load-
bearing, and both were reproduced as live failures before the numbers were
trusted: a config OBJECT with no `files` key, and a filename outside the
Linter's `cwd`, each return a single `ruleId: null` "No matching configuration
found for …" message — a result that is byte-for-byte indistinguishable from a
clean file if you only count reports. The run asserts a zero count of those, a
zero fatal count (a parse failure yields ONE message and ZERO rule executions),
and a must-fire positive control inside each repo's `cwd` before any corpus file
is read. One corpus, `typescript-eslint`, trips the fatal assert with 318 of
2,620 files: its fixture tree contains deliberate syntax errors. No rule ran on
those files, and they are excluded from the counts above.
