# SARJ024 `no-repeated-string-literal` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_repeated_string_literal.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

The same long, *structured* string literal appearing in two or more different
functions of a module is a real maintenance hazard: when one copy is edited the
others silently drift, and (unlike SQL/log/prompt scaffolding) the strings that
qualify here cannot plausibly be equal by coincidence. Derived from the
magic-values audit corpus ("Repeated Complex String Literal").

The rule is deliberately narrow — it fires only where cross-site drift is a
genuine bug, never on coincidentally-equal prose. Three filters combine:

1. **Structured only.** A literal qualifies only if it carries structural signal
   that makes coincidental equality near-impossible:
   - it contains a newline (multi-line SQL / prompt templates), OR
   - it matches an *uppercase* SQL keyword (`SELECT`, `FROM`, `WHERE`, …) —
     matched case-sensitively so prose ("...criteria *from* the prompt") does
     not trip it, only real SQL does, OR
   - it is a bare snake_case / dotted identifier (`^[a-z_][a-z0-9_.]*$`), i.e. a
     DB constraint / index / key name reused across statements.
   Plain user-facing error messages, log lines, and spoken prompts carry none of
   these — two different-intent messages that happen to be equal (e.g. a
   `get_user_error_message` mapping two distinct error codes to one sentence) are
   *not* flagged, so a shared constant can never wrongly couple them.

2. **Cross-function only.** The occurrences must span at least two distinct
   enclosing functions/methods. Two uses inside one function (or several
   module-level constants) are edited together and moving them to the module top
   buys no drift protection — that is pure locality loss, so it is excluded.

   This is the *only* count threshold. An earlier revision also demanded three
   total occurrences, which made the rule fire on nothing at all: 0 findings in
   the 2,657-file third-party corpus and 0 across the whole first-party Python
   tree. Dropping to "two distinct functions" costs no precision — the corpus
   then yields exactly one finding, `fastapi/openapi/models.py:39`, where a
   two-line "email-validator not installed" warning is duplicated verbatim
   between `EmailStr.validate` and `EmailStr._validate` and would silently drift
   if either were reworded. Cross-function drift *begins* at two copies; the
   third was arbitrary, and precision here is carried by filter 1, not by counting.

   THIS IS A CROSS-PACKAGE CONTRACT. The TS port
   (`packages/typescript/src/rules/no-repeated-string-literal.ts`) had kept the
   abandoned three-occurrence gate, so a literal used exactly twice fired here
   and was clean in `.ts` — the same code judged differently by file extension.
   Re-measured and converged 2026-07: requiring three occurrences would drop 15
   of the 18 findings over two first-party repos + django/fastapi/celery, and the
   dropped ones are true positives — one first-party store module repeats a
   `SELECT stage FROM … FOR UPDATE` verbatim between two sibling atomic-submit
   methods, and another repeats a 10-column `SELECT … JOIN …`
   between two methods. TS dropped its gate instead; its corpus delta was 0.
   Do not re-introduce a total-occurrence threshold in either package without
   re-running both sweeps.

3. **Exclusions.** f-string fragments (`ast.Constant` inside `JoinedStr`),
   docstrings (first statement of module/class/function), strings under an
   OpenAPI/pydantic scaffolding keyword (`examples=`, `description=`, `title=`,
   `summary=`), and strings in **type-annotation position** — parameter and
   return annotations, `x: T = ...` annotations, and anything inside an
   `Annotated[...]` subscript.

   The scaffolding-keyword and annotation exclusions cover the same category:
   documentation deliberately duplicated across sibling declarations. A string
   in annotation position is either a forward reference or PEP 593 metadata;
   neither is a value that can drift into a runtime bug, and a mismatch between
   copies is a type error the type checker already reports.

   Corpus evidence (2,657 files of fastapi / pydantic / black / sqlmodel / rich /
   flask / httpx / requests / anyio): **all 499** pre-guard findings were
   `Annotated[...]` metadata — 494 inside PEP 727 `Doc(...)` blocks and 5 inside
   `deprecated(...)`. fastapi documents every `APIRouter` verb with a verbatim
   copy of the same `Doc()` block, so one paragraph about `response_model`
   recurs once per HTTP method: `fastapi/applications.py:2018` (`put`),
   `:2396` (`post`), `:2774` (`delete`), `:3147` (`options`), `:3520` (`head`),
   `:3893` (`patch`), `:4271` (`trace`), and the same shape in
   `fastapi/param_functions.py:1657` (`Form`), `:1972` (`File`),
   `fastapi/security/api_key.py:186`. Hoisting those to a module constant would
   destroy the docs they exist to render. After the guard the corpus yields 0
   findings, and the only non-annotation repeats that survive every other filter
   are three prose strings the *structured* filter already rejects
   (`pydantic/main.py:786`, `rich/progress.py:148`, `sqlmodel/_compat.py:139`).

Each occurrence after the first gets its own diagnostic, so a deliberate
duplicate can be suppressed per-line with `# sarj-noqa: SARJ024 — <reason>`.

Skipped entirely: `conftest.py`, test files (`test_*.py` or under a `tests/`
directory) — fixtures legitimately repeat literal payloads.
* **generated files** (`_paths.is_generated`). Their layout is the
  generator's, and re-running the generator discards any edit, so a finding
  there can never be acted on in place. Measured on the 69 `DO NOT EDIT`
  files git-tracked across two first-party repos — a single Speakeasy-generated
  SDK package under `python/sdk/src/` accounts for all of them.

## Implementation notes

### `_annotation_exprs`

Covers parameter annotations, return annotations, `x: T = ...` annotations,
and any `Annotated[...]` subscript wherever it appears (including a type
alias assigned at module level).
