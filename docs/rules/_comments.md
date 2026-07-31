# `_comments` — evidence

Shared helper. This file holds what the code cannot: the measurements behind
each threshold, the false-positive families the guards exist to stop, and the
alternatives that were rejected.

Shared comment analysis for the comment-hygiene rules
(`no-comment-cruft`, `no-restated-comment`, `no-restated-jsdoc`,
`no-trailing-value-narration`) — the TypeScript twin of the Python
`rules/_comments.py`, kept signal-for-signal identical so the two languages
cannot drift on what counts as a comment worth keeping.

**The protected class.** Nine deterministic signals that mark a comment as
carrying something the code cannot: an external reference, a version pin, a
number with a unit, a causal connective, a negation of the obvious, an
upstream-quirk word, a concurrency/invariant term, security reasoning, or a
vendor proper noun with *ascribed behaviour*. Measured over a 37,918-comment
corpus from nine repos: the nine protect 40/40 hand-picked best comments and
leak ~1% of the hand-classified cruft list.

The class is an **EXEMPTION FLOOR, never a test**. `isProtected` returning
false says nothing about a comment — across pydantic / trio / attrs it matches
only 18-35% of the comments a human called valuable. Every use is of the form
"if protected, do not flag". Inverting it into "unprotected, therefore delete"
would condemn two thirds of the best comments in those libraries.

## Evidence relocated from the source

### `PROTECTED_SIGNALS`

S9 — a vendor proper noun with *ascribed behaviour*. A vendor name as the mere
object of a narration verb ("Create the prompt for Gemini") is NOT protected;
that distinction is what holds the leak rate at ~1%.

### `/**`

True when a comment cites a ticket, URL, RFC/PEP/CVE, or issue number
(signal S1 alone). Naming where a decision is recorded is the one thing code
cannot do, and it separates an owned scoping note ("EN-only for now — AR needs
audio (PROJ-249)") from an unowned admission ("hacky, fix later").

### `// --- the verb-opener restatement shape (shared with `no-co`

Exact or stemmed match only. Prefix matching is deliberately absent: it is
what sank the first attempt at this shape (PR #98), where `service` matched
`locationService` and drove the false-positive rate to ~60%.

