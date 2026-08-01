# SARJ068 `prefer-fstring-over-concat` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_fstring_over_concat.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`"user " + name + " failed"` is worse than `f"user {name} failed"` in four
concrete ways: every non-`str` operand needs an explicit `str()` wrapper and
raises `TypeError` the day someone forgets one; the literal fragments' leading
and trailing spaces are invisible at a glance (`"user "` vs `"user"`); a chain
of three or more `+` reads as arithmetic rather than as a template; and the
value's shape is not recoverable by any tooling that understands format
strings. The f-string is one expression whose final text is readable in source
order.

WHY THIS IS NOT ALREADY COVERED BY RUFF
---------------------------------------

Measured, not remembered: a probe file was run through `ruff check` with this
repo's `ruff.strict.toml` (`select = ["ALL"]`, `preview = true`). Of the
string-formatting rules that sound relevant, none flags a literal concatenated
with an expression:

* `ISC001/002` cover *implicit* concatenation (`"a" "b"`), and `ISC003` covers
  *explicit* concatenation of string LITERALS only — it fired on
  `("long one " + "long two")` and stayed silent on `"prefix" + name`,
  `"id=" + str(x)`, `name + "!"` and `"a" + name + "b" + path + "c"`. Literal +
  literal is ruff's; literal + expression is nobody's — **except for one shape,
  where the two do double-report.** An f-string operand is a runtime expression
  to this rule and a string literal to ruff, so `f"{name}={value} " + "suffix"`
  trips both. Measured over four corpora: celery 1 of 89 findings, mlflow 18 of
  667, saleor 7 of 406, django 0 of 368 — 26 shared lines in 1,530, or 1.7%.
  `mlflow/mlflow/utils/server_cli_utils.py:29` is the canonical instance. An
  earlier version of this docstring claimed the two "never overlap"; that was
  wrong, and the measurement above replaces it. The remedies differ (ruff wants
  implicit concatenation, this rule wants one f-string), so the reports are
  complementary rather than contradictory, but a reader seeing both on one line
  should apply this rule's and let the ISC003 finding fall out with it,
* `UP031` (`%` → f-string) and `UP032` (`.format` → f-string) fired only on the
  `%`/`.format` spellings; `+` is untouched,
* `FLY002` fired only on a static `str.join` of literals,
* `G003` fired on `logger.info("x " + name)` — see the logging exemption below,
  which is why this rule stays silent there and there is no double report,
* `S608` fired on `"SELECT * FROM " + table`; that literal shape is exempted
  here rather than double-reported (see below).

RELATIONSHIP TO SIBLING SARJ RULES
----------------------------------

* **SARJ002 `inefficient-string-concat-in-loop`** is a *performance* rule about
  `s += x` / `s = s + x` STATEMENTS whose target accumulates across loop
  iterations — O(n²) growth, remedied by `"".join`. This is a *readability*
  rule about `+` EXPRESSIONS anywhere, remedied by an f-string. The populations
  barely intersect: SARJ002 needs a self-referential assignment inside a loop,
  this rule needs a literal operand and does not care where it sits,
* **SARJ017 `no-fstring-in-log`** says the *opposite* inside logging calls:
  stdlib/loguru logging wants a constant template with lazy `%s`/keyword
  parameters, so an f-string there is the defect. Recommending an f-string for
  `log.info("call " + cid + " failed")` would produce code SARJ017 immediately
  flags. This rule therefore never fires inside a logging call — the logger
  receiver is resolved with the same shared `_logging.is_logger_expr` helper
  SARJ012/SARJ017 use, so the three rules can never disagree about what a
  logger is. `warnings.warn(...)` is deliberately NOT exempt: it formats
  eagerly, so an f-string is correct there.

Fires on the OUTERMOST `+` chain (never once per operand) when ALL hold:

* every `Constant` operand in the flattened chain is a `str` — that literal is
  the only type evidence available without a type checker, and
* at least one operand is a runtime expression (`Name`, `Attribute`, `Call`,
  `Subscript`, an f-string, …).

CORPUS EVIDENCE
---------------

Swept over 6,155 Python files — two first-party repos, repo A (1,179) and repo B
(502), plus django (2,927), fastapi (1,130), celery (417). 717 raw candidates;
the guards below removed 181 of them (25%), leaving 536: repo A 24, repo B 15,
django 379, fastapi 29,
celery 89. A 25-hit manual sample spread across all five corpora classified 24
true positives and 1 false positive (4%) — the survivor is noted under the
character-set bullet below. Separately, 773 chains were rejected outright by the
"every literal must be a `str`" test (integer arithmetic and `bytes`
concatenation reaching a `+` with a literal in it); without that test the rule
would have fired on more arithmetic than string building.

A later external audit re-swept 40,336 files across 20 repos (the five above
plus three more first-party repos, this repo, airflow, dagster, litellm,
saleor, mlflow, langchain, superset, zulip, prefect, warehouse, sentry-python)
and confirmed the sampled FP rate at 4.5%. That sweep found four residual FP
shapes, each now guarded and each measured at **zero** true-positive cost on the
first-party repos (repo A 24, repo B 15, repo C 23, repo D 7, repo E 8
before and after; repo labels are stable within this docstring only):
`or`/`and` operands (12 hits), ORM expression operands (3),
`%`-format template literals (10) and whitespace-only blob gluing (12; one hit
is shared with the ORM guard). Total 4,882 → 4,846 across the 20 repos, with no
hit gained; 574 → 565 across the eight repos of the standard sweep, whose
first-party counts are unchanged.

Deliberately NOT flagged:

* **any chain containing a non-`str` literal.** `x + 1`, `b"GET " + path`,
  `offset + 0x20`. With no types, a string literal in the chain is the only
  evidence the `+` is concatenation at all; a numeric or `bytes` literal is
  positive evidence it is not, and `bytes` has no f-string equivalent
  (`f"..."` is `str`). This is also what keeps `a + b` — two bare names that
  could be ints, lists, `timedelta`, `Path`, numpy arrays or a domain type with
  an `__add__` overload — permanently silent: no literal, no diagnostic,
* **logging calls** (mandatory, see SARJ017 above). `logger.info("x " + name)`,
  `log.bind(...).error("x " + name)`. Ruff's `G003` already reports these with
  the correct `%s`-parameter advice. Keyword arguments are exempt too, so
  `logger.info("done", detail="x " + y)` is silent — the whole call is the
  logging boundary. 4 hits,
* **a literal containing `{` or `}`.** The f-string rewrite has to double every
  brace, which is exactly the transcription error the rule is meant to prevent.
  This is what regex assembly and format templates look like in practice: one
  first-party pronunciation module builds four `re.compile` patterns as
  `r"(\d{4,6})(?!\s*" + CURRENCY_TERMS + r")"`, and a first-party logging
  helper returns `format_string + "\n{exception}"` — a loguru
  template whose braces are *meant* to survive. A first-party URL helper
  (`path.replace("{" + key + "}", ...)`) is the same shape. 12 hits,
* **an operand that is a `.join(...)` call.** `"header\n" + "\n".join(rows)`
  becomes `f"header\n{'\n'.join(rows)}"` — a quoted, backslash-bearing
  expression nested inside the f-string, which was a syntax error before 3.12
  and is unreadable after. The `+` spelling is the better one. This is the
  dominant assertion-message idiom in both house repos: three route-coverage
  test modules in one first-party repo, three sites apiece, and a query builder
  in another (`"WHERE " + " AND ".join(conditions)`).
  43 hits — the single largest guard
  after string repetition,
* **a chain that only glues opaque blobs together with whitespace**: every
  literal fragment in it is whitespace — including the constant parts of any
  f-string operand, so a chain carrying real prose inside an f-string still
  fires — AND at least one operand is a call carrying a string-literal argument.
  This is the general case of the `.join` bullet above. There is no prose for
  the f-string to make readable, and the rewrite has to nest a quoted call
  inside a placeholder: this repo's own
  `tests/rules/test_over_mocked_test.py:65` glues two source fixtures with
  `_patches(6).replace("test_thing", "test_a") + "\n\n" + ...`, whose f-string
  form nests two quoted `.replace(...)` calls; airflow's
  `scripts/ci/prek/supported_versions.py:63,73` is `"\n" + tabulate(rows,
  tablefmt="github", ...)`; mlflow's `dev/flavors/src/flavors/_matrix.py:248` is
  `"\n" + f" {title} ".center(length, "=") + "\n"`. 12 hits. The broader
  spelling — *any* 3-or-more-operand chain whose only literals are whitespace —
  was measured and rejected: it removes 170 hits but costs 6 first-party true
  positives (two sites in one first-party request-handler module and their
  siblings, which do carry prose inside their f-string operands),
* **an operand that is string repetition** (`"A" * N + " tail"`,
  `"x" + "\n" * 51 + "y"`). `f"{'A' * N} tail"` is strictly worse than the
  original. Found at three sites in one first-party store test and two in
  another first-party conversation test, plus django's
  padding and separator-bar helpers. 67 hits, the largest single guard,
* **a two-operand chain whose only literal is whitespace** — `payload + "\n"`,
  `"\n" + body`. Appending a terminator is not string building, and
  `f"{json.dumps(payload, indent=2)}\n"` is not an improvement on
  `json.dumps(payload, indent=2) + "\n"`. Found identically in five ratchet
  scripts in one first-party repo and four in another
  (`scripts/check_coverage_ratchet.py:72` and
  siblings). Three or more operands still fire, because `a + " " + b` really is
  clearer as `f"{a} {b}"` — unless the blob-gluing bullet above applies. 32 hits,
* **a chain that is the left operand of `%`.** `("%0" + width + "d") % (i, line)`
  assembles a *format template*, not a message; rewriting the left side as an
  f-string leaves a confusing f-string/`%`-format hybrid. This is the positional
  companion to the conversion-specifier bullet below: it catches templates whose
  literals carry only a width or flag fragment (`"%0"`, `"d"`), which no
  specifier regex can recognise, and needs the `%` to be applied on the spot.
  django's `template/defaultfilters.py:240,243,292`. 3 hits,
* **an operand that is a translation or safe-string call** (`_`, `gettext`,
  `gettext_lazy`, `ngettext`, `pgettext`, `format_lazy`, `lazy`, `mark_safe`,
  `format_html`). Interpolating a lazy translation proxy into an f-string forces
  it to render at concatenation time instead of at display time, which is the
  entire bug `format_lazy` exists to avoid; interpolating a `SafeString` returns
  a plain `str` and silently drops the "already escaped" marking. This is a
  behaviour change, not a restyle. 1 hit,
* **an operand that is a conditional expression or a boolean fallback.**
  `("-" if desc else "") + "datefield"` becomes `f"{'-' if desc else ''}datefield"`,
  which buries a branch inside a format placeholder; `(value or "") + "\n"` and
  `(lang or "") + ":" + code` bury exactly the same branch in exactly the same
  place, spelled `or` instead of `if`. django's `db/models/query.py:1617,1650`,
  `db/backends/oracle/base.py:324` and `tests/admin_views/tests.py:304`, plus
  litellm's `llms/snowflake/chat/transformation.py:369` and zulip's
  `zerver/views/documentation.py:53`. 7 + 12 hits,
* **an operand that builds an ORM / SQL expression object** — `F(...)`,
  `Value(...)`, `literal(...)`, `Concat(...)`, `RawSQL(...)`, `bindparam(...)`,
  or an attribute call rooted at `func` / `expression` / `sa` / `sqlalchemy`.
  The `+` there is `Concat` by operator overload on a query node, not string
  concatenation, and an f-string would render the expression's `repr` at build
  time instead. This is behaviour-breaking, not cosmetic: django's
  `tests/expressions/tests.py:1299` is the SQL-injection regression test
  `F("num_chairs") + "1)) OR ((1==1"`, and rewriting it as an f-string silently
  deletes the payload the test exists to prove is escaped. Also superset's
  `models/core.py:1336` (`@perm.expression`) and a `func.nullif(...)` label in
  one of its migrations. 3 hits,
* **a literal carrying a `%`-conversion specifier** (`"%s"`, `"%r"`,
  `"%(asctime)s"`, `"%.2f"`). `"SELECT %s" + suffix` and
  `"%(asctime)s %(hostname)s " + name + ": %(message)s"` assemble a `%`-format
  template whose consumer applies it later, so the chain is not the finished
  string; an f-string here produces an f-string/`%`-format hybrid. This is the
  literal-side companion to the `%`-left-operand guard above, which only sees
  the case where `%` is applied on the spot. URL-encoded octets are NOT
  specifiers — a `(?![0-9A-Fa-f]{2})` lookahead keeps `"%2F" + segment[1:]`
  (dagster's `_core/storage/upath_io_manager.py:28,52`) firing. django's
  `utils/formats.py:75`, `contrib/gis/db/backends/mysql/operations.py:28`,
  `tests/backends/tests.py:84,296,301` and zulip's `zproject/dev_settings.py:75`.
  10 hits,
* **a literal ending in a SQL keyword** (`"SELECT * FROM " + table`,
  `"... WHERE id = " + uid`). Ruff's `S608` already reports that exact shape as
  an injection vector, and SARJ021 covers `SELECT *`; answering "use an
  f-string" would restyle an injection instead of fixing it, and this rule must
  not become a competing SQL rule. The keyword match is case-SENSITIVE, so
  prose like `"copied from " + src` is not mistaken for a query. 7 hits,
* **generated files** (`_paths.is_generated`). Re-running the generator
  discards any edit, so a style finding there can never be acted on — the same
  exemption SARJ002 makes. 5 hits, all inside one first-party repo's
  Speakeasy-generated SDK package.

Known and accepted (the 1 false positive in the 25-hit sample): a module-level
character-set constant composed from another constant — one first-party
validator-property test,
`_DIGITS_AND_LETTERS = _DIGITS + "abXY"`. There `+` reads as alphabet union and
the f-string adds nothing. Guarding it would require knowing the constant is a
character set, which the AST cannot tell from any other module-level string
constant; suppress it with `# sarj-noqa: SARJ068 — <reason>`.

## 2026-07 false-positive audit

Re-swept over 24,644 deduped files across 19 repos (6 first-party plus django,
celery, airflow, litellm, prefect, saleor, zulip, fastapi, pydantic, rich, httpx,
requests): **3,401 findings**, 76 of them first-party. A seeded random sample of
50 read against source gave **19 true positives, 9 false and 22 arguable — an 18%
false-positive rate**.

**Exactly ONE guard survived that read.** Two more were built, measured and
rejected; they are recorded below so nobody rebuilds them.

### The guard that landed: a multi-line chain with a comment inside its span

`prefect`'s deployment CLI tests interleave `# Enter invalid interval` /
`# Enter valid interval` between the operands of one chain
(`tests/cli/test_deploy.py:3055` and `:6372`); collapsing it to an f-string
DELETES those comments, which is a loss of information rather than a restyle. The
test is positional — a COMMENT token whose line falls between the chain's first
and last — so a trailing comment on a single-line chain is untouched. Tokenizing
is deferred until a multi-line chain has already earned a diagnostic, so files
without one pay nothing. **58 findings, 1 first-party. 3,401 → 3,343**,
first-party 76 → 75.

### REJECTED: a regex-metacharacter guard

Exempting a chain whose literals carry regex metacharacters (`\d`, `.*`, `[^`,
`(?`, an anchor) was implemented and then reverted.

It suppressed **38 findings of 3,401 (1.1%, 1 first-party)** — and it collided
head on with `test_fires_when_the_braces_are_removed`, an *upper-bound* test whose
whole job is to pin the `{`/`}` guard narrow. That test asserts
`pattern = r"\s*" + re.escape(key) + r"\s*"` still reports, and the guard made it
stop. **Overriding an upper bound is how a guard silently widens into a no-op**,
which is the failure mode this rule's tests exist to prevent.

The premise was also weaker than it looked: `rf"\s*{re.escape(key)}\s*"` is
ordinary, idiomatic Python, so a concatenated regex is not a shape where the
rewrite is unavailable — merely one where an author might reasonably prefer the
concatenation. That is a style preference, not a false positive, and 1.1% of
volume does not buy the right to retire a deliberate test.

### REJECTED: a nested-quoted-call guard

For a two-operand chain whose single dynamic operand's call spine carries a
string-literal argument, drop `_is_blob_glue`'s "every literal is whitespace"
requirement and suppress. The argument for it is real —
`django/django/db/models/fields/__init__.py:654` is
`"django.db.models" + path.removeprefix("django.db.models.fields")`, whose
f-string form buries a quoted call carrying a nearly identical string next to the
literal it duplicates, and `django/tests/modeladmin/models.py:52`
(`strftime("%Y")[:3] + "0's"`) additionally drags an apostrophe into the template.

It is rejected on cost. **165 findings, 6 of the 75 first-party (8%).** That is
the same price this file already refused once: the broader blob-glue spelling was
measured at 170 hits for 6 first-party true positives and turned down, and taking
this one would be deciding the opposite thing for the same number. The wider "any
operand count" spelling is worse still — **195 findings, 13 of 75 first-party
(17%)**. The two-operand shape is also already pinned as FIRING by an explicit
unit test (`dotted-path`), which is the house saying out loud that it wants the
report.

### The largest cluster, deliberately left firing

1,309 findings (38.5%) are the two-operand `<expr> + "<literal with no
whitespace>"` suffix append — `file_path + ".original"`. None of the four
justifications at the top of this file applies to it: there is no coercion to
delete, no invisible spacing, no chain to misread as arithmetic. It is
nonetheless NOT a false positive — it is a house-style call about whether a
one-fragment template is worth an f-string — and it is deliberately not guarded.
A house that disagrees should say so with a per-file suppression, not by
narrowing the rule.

## Implementation notes

### `_flatten`

Iterative on purpose. `a + b + c + ...` parses as a left-nested `BinOp`
spine one level deep per operand, so a recursive walk costs a Python frame
per `+`. CPython's parser builds that spine without recursing and raises
nothing, but a recursive flatten hits the default 1000-frame limit at
~1000 operands — and a `RecursionError` here escapes `check()`, which only
`SyntaxError` is caught around, taking down the whole lint run rather than
skipping one file. The longest real chain measured across 43k files is 27
(`dagster-graphql/schema/__init__.py:52`), so this is a guard against a
generated or minified file rather than against ordinary source.
