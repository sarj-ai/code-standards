# SARJ049 `no-restated-comment` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_restated_comment.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

    # Get order by reference
    order = await self._store.get_order_by_reference(reference, tenant_id)

Every content word of the comment is already an identifier on the line below.
It cannot go out of date usefully — it can only go out of date silently, and a
reader who scans it learns nothing they would not have learned from the code.
Delete it, or replace it with the *why* (what the caller must know, what breaks
if the order changes, which ticket decided the shape).

This is deliberately NOT part of SARJ016. One first-party repo enforces SARJ016
at `error`
through a caret pin, so folding a new detector into it would land uncontrolled
in a consumer's CI on the next patch release; a separate code can be enabled,
baselined and dropped on its own.

**What makes it safe.** The first attempt at this shape (an earlier TypeScript
prototype) corroborated by substring — `service` matched `locationService` — and produced
933 hits at a ~60% false-positive rate. Coincidental token overlap is the
failure mode, so every one of these guards is load-bearing:

- **Zero information, not "mostly".** EVERY content token must appear on the
  line. One unmatched word means the comment carries something the code does
  not, and it stays. Matching is exact-or-stemmed; there is NO prefix matching.
- **Single-line comment only.** A run of `#` lines is a paragraph, and a
  paragraph's first line sharing words with the code below is a coincidence of
  where the sentence broke.
- **Simple statement only.** A comment above a `def`, a `class`, an `if`, a
  `for` or a `try` is labelling a *region*; the words it shares with the first
  line of that region are incidental.
- **Not a group label.** When the statement below is followed by a same-indent,
  same-shape sibling, the comment heads a run (`# Constants` over eight
  assignments), and deleting it loses the grouping.
- **Not inside a bracketed expression.** A comment at bracket depth > 0 labels
  an *element* of a list, dict or call — one `State(...)` in a list of test
  cases, one entry in a `__all__` group — and the element's own words are what
  it labels. `_comments.nested_comment_lines` exists for exactly this reading.
- **No negation in the code.** The comment-side negation guard below has a
  mirror: when the CODE expresses a property negatively and the comment states
  it positively, the comment is doing a translation the code cannot.
  `# The task is queued` over `assert not kubernetes_executor.task_queue.empty()`
  (airflow) passes the zero-information test only because `not` and `no` are
  stopwords for the tokenizer.
- **Protected class exempt.** Anything carrying a ticket, URL, unit, causal
  connective or the other `_comments` signals is left alone.
- **≤8 words**, no `?` (a question is a note to a reader), no non-ASCII prose
  (the tokenizer cannot read Arabic, so the zero-information test would be
  vacuously true), no commented-out code (SARJ016 owns that), no banner shapes.

**Measured** (this implementation, not the prototype). repo A **0**; repo B
**29** over 20 distinct comment texts; pydantic **2**, trio **2**, attrs **0** —
(repo labels are stable within this docstring only)
and those four are genuine (`# set_inheritable` above `s1.set_inheritable(False)`,
`# get_inheritable` above `assert not s1.get_inheritable()`).

**The 33-finding sweep those numbers came from was too small to see the failure
mode.** A later sweep over home-assistant (18,069 files, 348 hits) and airflow
(7,656 files, 165) produced 513 findings; 60 were sampled at random and each read
against its source. **47 true positives, 13 false — a 21.7% false-positive rate**,
not the 0% the small corpora suggested. The two guards above are what a labelled
evaluation showed to be free (they suppress 2 of the 13 false positives and 0 of
the 47 true ones); three other candidate guards were built, measured and
*rejected* for costing more recall than they bought:

* *comment matched only through a string literal* — 7 FP but 6 TP, a wash
  (`# Set false` over `variables_set(["variables", "set", "false", "false"])`).
* *comment heads a blank-line-separated paragraph of ≥2 statements* — 9 FP, 12 TP.
* *a sibling comment nearby shares a content word* — 7 FP but **33** TP. Two
  restatements in one function usually name the same domain noun; the shared word
  is the subject matter, not a section structure.

The residual **19%** is one shape the tokenizer cannot separate: a section label
heading a block in a test body (`# test tamper sensor` over the first of six
asserts, `# Test with domain only` over the first of a three-block series). Read
as a hit rate that is **0.8% of eligible single-line comments** in both external
corpora — well under the 4.7%-of-log-calls that got SARJ055 dropped for being a
professional convention — so the shape is rare, not idiomatic. But a house
enabling this at `error` is choosing to reject a test-body section label, and
should say so out loud rather than believe the 0% number.

Getting there cost five guards, each added at the site that produced it and each
with a regression test: the code-keyword arm of the commented-out check (a
disabled `assert` above the assertion that replaced it), the call/assert
statement shapes (a label heading a run of bare calls), modality / lead-in /
emphasis, `_ACTION_STMT_RE` (a label over a data declaration — every remaining
repo B false positive), and the two-content-token floor (`# Hashing.` over an
assertion group in attrs).

Suppress an intentional case with `# sarj-noqa: SARJ049 — <reason>`.

## Implementation notes

### `_is_group_label`

`index` is 0-based into `lines`. The statement's extent is found by bracket
balance so a multi-line call is skipped whole; if what follows is a
same-indent statement of the same shape, the comment above labels the run
rather than the one line.
