# SARJ016 `no-comment-cruft` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_comment_cruft.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

Code expresses the *what*; comments are reserved for the *why*. Three comment
shapes carry no *why* and are pure noise — they are detected deterministically
here (the fuzzier "this comment merely restates the code" judgment stays in the
readability audit, not this rule):

1. Commented-out code — a standalone comment whose text parses as Python:
       # return early_result
       # for row in rows:
   Delete it; git history remembers.

2. Section-banner / region markers:
       # ============================
       # region helpers
   Structure code with functions, not ASCII rules.

3. Leading file-header preamble — a run of 4+ standalone comment lines at the
   top of the file before any code **that contains no prose sentence**. Use a
   module docstring for the *why*, not a block of `#` lines.

   The "no prose sentence" guard is load-bearing, and it is a CROSS-PACKAGE
   CONTRACT shared with the TS port's `fileHeaderPreamble` arm
   (`packages/typescript/src/rules/no-comment-cruft.ts`). The naive test — 4+
   consecutive comment lines, nothing else — penalises *syntax* rather than
   *content*, so it flags a module header precisely when someone bothered to
   write one. TS measured this first on a 42k-LOC codebase: 11 of 15 hits were
   the repo's best documentation and exactly 1 was genuine (an ASCII banner
   `sectionBanner` already covers). Python shipped the naive test for longer, and
   re-measuring it in 2026-07 over two first-party repos + django/fastapi/celery
   reproduced the same result even more starkly: **7 hits, 7 false positives,
   0 true positives.** Every one was a prose header a module docstring should
   simply absorb, not delete:
     - `django/django/contrib/auth/urls.py:1` — why this URLconf exists at all
       ("normally mapped in the AdminSite instance … provided as a convenience").
     - `django/tests/deprecation/internal.py:1` — the fixture's whole contract
       (which functions call `warn_about_external_use`, and at what stack depth).
     - `django/tests/test_sqlite.py:1` — how to point the suite at another
       backend, with the contributing-docs URL.
     - `django/scripts/manage_translations.py:2` — the script's 20-line CLI
       reference, `$ python scripts/manage_translations.py lang_stats -l es`.
     - `django/tests/i18n/exclude/__init__.py:1`,
       `fastapi/tests/test_no_schema_split.py:1` (links the upstream discussion
       and issue the regression pins), `celery/examples/resultgraph/tasks.py:1`
       (a `>>>` usage example).
   After the guard the corpus yields **0** preamble findings and the other two
   arms are untouched (494 → 487 total, delta exactly those 7). The arm is kept
   rather than deleted so it stays a preventive ratchet against a genuinely
   content-free header (a stack of bare `# author:` / `# version:` labels), and
   so the two packages keep one definition of the shape — deleting it here would
   re-open the divergence from the other side.

   A note for the next auditor: an independent audit reached the same conclusion
   from the SQL side, observing that the naive test would hit 31 of 239 `.sql`
   files, all well-documented destructive migrations. No SQL rule implements this
   concept (`sarj_sql_lint` has no comment-cruft rule), so there was nothing to
   change there — but if one is ever added, it inherits this guard.

Deliberately NOT flagged: trailing/standalone *prose* comments (the legitimate
"why"); code-shaped *illustrations* — a line that parses as Python but sits
under a prose lead-in (`# For example:`, a wrapped sentence) or carries
pseudo-code markers (`%sent%`, `[opt]`, `<FunctionBody>`, `...`); and directive
comments — `# type:`, `# noqa`, `# sarj-noqa`,
`# pragma:`, `# pyright:`, `# mypy:`, `# fmt:`, `# isort:`, `# ruff:`,
`# nosec`, `# TODO`, `# FIXME`, `# language=` (IDE injection), shebangs, and
coding declarations.

Also NOT flagged (famous-repo sweep hardening):
- generated files (`_paths.is_generated`) — their banners are the
  generator's warning header, not hand-written cruft;
- a punctuation-only "banner" directly beneath a texty comment line — that is
  an RST-style heading underline or an ASCII-diagram row inside a prose comment
  essay (trio's epoll/socket design essays), not a code-section separator;
- step narration that carries a rationale marker (`because`, `since`,
  `so that`, `otherwise`) — "First, take the lock, because ..." is a *why*.

Not flagged either (2,657-file sweep of fastapi/pydantic/black/sqlmodel/rich/
flask/httpx/requests/anyio — 745 findings triaged, 404 were false positives):
- `# insert_assert(...)`, the pytest-examples code-regeneration recipe. 383
  hits, every one in pydantic (`pydantic/tests/test_types.py:180` and 239
  identical siblings), always parked directly above the assertion it writes.
  `insert_assert` is never *called* anywhere in that repo — the comment exists
  to be uncommented, so "delete it, git history remembers" is advice about a
  line git never held.
- Every line of an announced snippet block: a colon-terminated prose lead-in
  (`# Original implementation:`) arms the rest of its contiguous comment run.
  Judging lines one at a time saw only the row directly above and missed the
  announcement — `flask/src/flask/helpers.py:343` is separated from its lead-in
  by a blank `#`, `black/src/black/comments.py:621` indents a second snippet
  row under the first, and `black/src/black/linegen.py:1862-1871` interleaves
  four `with`-statement grammar examples with `#     ...` rows. 8 hits. A bare
  block keyword (`# else:`) arms nothing: it announces nothing, it *is*
  commented-out code — `pydantic/pydantic/v1/mypy.py:895` stays flagged.
- Narration markers on a line whose predecessor ends mid-sentence — the tail of
  a wrapped prose comment, whose *why* sits in the rows above. 14 hits,
  including `pydantic/pydantic/json_schema.py:1046` (the whole comment is
  `# for now`, continuing two rows of explanation) and
  `black/src/black/concurrency.py:79` ("I know it's / not ideal, but ..."). A
  blank `#` ends the paragraph, so it continues nothing.
- A leading comment block with no letter in it at all — line art, not a
  preamble a module docstring could absorb. 1 hit: the requests logo at
  `requests/src/requests/__init__.py:1`.

Deliberately still flagged, after reading the sources: `# debug(v)`
(pydantic-core, 37 hits) is a commented-out print-debugging call, not a
regeneration recipe; fastapi's `# ====...` test-section rules (88 hits) and
pydantic's `# ~~~ BOOLEAN TYPES ~~~` (33 hits) are the very banners this rule
exists to remove; and keyword-argument-shaped labels (`# tls=True`,
`anyio/src/anyio/_core/_sockets.py:101`) keep firing because exempting the
no-space-around-`=` shape would have taken 9 genuinely dead lines with it
(`pydantic-core/tests/validators/test_url.py:1165-1167`) to spare 6 labels.

Two live false positives were found by running the shipped rule over the
corpus and are fixed here:
- the region check matched the bare WORD `region`, so a prose comment opening
  `# region, sector and type are HARD constraints when ...` (one first-party
  site, plus six TypeScript siblings) read as a folding marker. It now requires
  the marker SHAPE: no title, or a short unpunctuated one.
- `for now` fired on a ticket-bearing scoping note. A comment naming where the
  decision is recorded is doing the one thing code cannot, so protected-class
  signal S1 (ticket / URL / RFC / issue number) now exempts narration — at RUN
  granularity, because a scoping note puts its owner on the last line.

Extensions added in the same pass, each measured ZERO-hit on the first-party
repo that enforces this rule at `error` (an extension that fires there would
break a consumer's CI on a patch release):
- bare one-word section labels from a closed vocabulary (`# Constants`,
  `# Helpers`, `# Types`) — 22 corpus hits, 12 of 12 sampled were true;
- the `Helper function to ...` opener — 6 of 6;
- `Let's <verb>`, gated on a verb list so the third-person `lets` (which does
  real explanatory work) is untouched;
- Unicode box-drawing rules (`────────`) as banners — 34 corpus hits the ASCII-
  only check could not see;
- a numbered / `Phase N:` marker, but ONLY when the file carries exactly one.
  A run of them is a documented algorithm walkthrough, which is the kind of
  comment this rule exists to protect.

Suppress an intentional case with `# sarj-noqa: SARJ016 — <reason>`.

## Implementation notes

### `_is_prose_line`

Used to spot a doc/prose comment that immediately precedes a code-shaped
line: `# For example:` above `# result = {**a, **b}`, or a wrapped sentence
whose second line happens to parse as an expression. Such a line is an
illustration / prose continuation, not commented-out code.

### `_is_heading_underline`

An RST-style heading underline (`# Literature review` / `# -----------`) or
an ASCII-diagram row directly beneath a texty row lives INSIDE a prose
comment block — it is typography, not a code-section separator.

### `_is_redundant_narration`

`isolated_enumeration` is True when this comment is the file's ONLY
numbered/phase marker; a file with several is walking through an algorithm.
`nested` is True inside a bracketed expression, where a one-word label is
grouping the elements beneath it rather than signposting the file.

### `_is_sentence_continuation`

Narration is judged one line at a time, but a wrapped prose comment is one
thought spread over several rows. When the row above ends mid-sentence this
row is its tail (`# for now`, `# both ways for now.`) — the *why* lives in
the rows above, and flagging the tail points at a fragment. A blank `#`
ends the paragraph, so it does not continue anything.

### `_illustration_block_lines`

A colon-terminated prose line (`# Original implementation:`) announces a
snippet, and everything after it in the same contiguous comment run is that
snippet until plain prose resumes. Judging those lines one at a time misses
the announcement two rows up — flask's `# Original implementation:` is
separated from its snippet by a blank `#`, and black's f-string grammar
notes indent a second snippet row under the first.

A bare block keyword (`# else:`) is excluded: it announces nothing, it *is*
commented-out code.

### `_externally_referenced_lines`

Protected-class signal S1, applied at run granularity because a scoping note
puts its owner at the end: one first-party four-line canary comment ends
"EN-only for now — add an AR variant once AR audio exists (PROJ-249)", and
judging the last line alone read "for now" as an unowned admission. A comment
that names where the decision is recorded is doing the one thing code cannot.

### `_doctest_block_lines`

A commented doctest is documentation, not dead code, but its *expected
output* lines look exactly like commented-out code — `# URL('https://...')`
in httpx's `_client.py` is the canonical shape. Exempting only the `>>>`
lines would still flag the output beneath them, so the whole run goes.

### `_is_coding_cookie`

`# encoding=utf-8` / `# -*- coding: utf-8 -*-` are read by the interpreter,
not commentary, and `rich` carries them at the top of test modules.
