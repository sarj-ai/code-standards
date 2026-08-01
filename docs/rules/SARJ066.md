# SARJ066 `duplicate-test-body` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_duplicate_test_body.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`test_admin_can_delete` and `test_editor_can_delete` whose bodies are the same
three lines with `"admin"` swapped for `"editor"` are not two tests. They are one
test run twice, and the duplication has a running cost: the suite reports two
passing tests where one behaviour is covered, so the test count overstates the
coverage; and every future edit — a renamed fixture, an extra assertion, a
changed helper signature — has to be made N times, which is exactly the edit
people make N-1 times.

`@pytest.mark.parametrize("role", ["admin", "editor"], ids=["admin", "editor"])`
collapses them into one body with N cases, and (unlike the hand copy) a new case
is one list entry rather than a new function.

This is the copy-paste sibling of **SARJ041 `test-loops-over-literal-cases`**,
and the two are exact mirror images. SARJ041 fires when a *single* test hides N
cases inside a `for` loop over a literal table — too few test functions. This
rule fires when N *separate test functions* hold the same body — too many. Both
diagnostics ask for the same fix, `@pytest.mark.parametrize`, from opposite
sides. Where SARJ041 works inside one function, this rule is a whole-module
grouping. The `ids=` advice in the message is the bridge to **SARJ042
`parametrize-case-needs-id`**: collapsing named scenarios into a table loses the
scenario names unless `ids=` carries them over, and a nameless case table is
SARJ042's problem.

Fires when ALL of these hold:

* the file is a test file (`is_test_path`), and is not generated,
* the tests are **pytest-style**, not `unittest.TestCase` methods,
* two or more `test_*` functions **in the same container** — the module body, or
  the same class — normalize to the same body shape,
* the shared body is **substantive**: at least 3 statements counted over the
  whole body subtree, docstring excluded. Two-statement tests
  (`x = f(); assert x`) are similar by nature, and grouping them measures
  nothing,
* the functions agree on everything that is not the body: same `async`-ness,
  same parameter list, and byte-identical decorators.

Body shapes are compared by hashing into a dict, never by comparing functions
pairwise, and in two stages: a cheap per-function outline (one traversal, no
copying) buckets the candidates, and the expensive normalization runs only
inside a bucket that already has two members. On the worst real test module
measured that is the difference between 53 and 19 ms/1k LOC, for identical
findings. There is no cap on module size and nothing is ever truncated. The
normalization erases exactly two things:

* **every constant** collapses to one placeholder, so the literal that differs
  between the copies (`"admin"` vs `"editor"`, `200` vs `404`) does not defeat
  the match. The original values are kept in order, which is what lets the
  message name what actually differs,
* **every name bound inside the body** (assignment, `for`, `with ... as`,
  `except ... as`, walrus, comprehension target) is renamed to `v0, v1, …` in
  first-appearance order, so `user = ...` and `u = ...` are the same shape.

Everything else is kept verbatim, and that is the load-bearing half of the
design: attribute names, keyword-argument names, operators, and any name the
body does *not* bind — module-level constants, imported helpers, enum members,
exception classes, the function under test — all stay. `assert normalize_phone(x)`
and `assert normalize_email(x)` are different shapes; `assert f(x) == CANONICAL`
and `assert f(x) == LEGACY` are different shapes. Only a difference that a
`parametrize` argument could actually carry is erased.

Corpus evidence. Measured over five populations — repo A (3,472 substantive test
functions), repo B (2,307), django (13,499), fastapi (2,076), celery (2,692) —
holding the group threshold at 2 (repo labels are stable within this docstring
only):

    repo A 61 (1.8% of its tests)   repo B 33 (1.4%)   django 0
    fastapi 387 (18.6%)             celery 40 (1.5%)

Before the `unittest.TestCase` guard the same run fired 983 times; that one
guard removed all 462 of the difference (458 in django, 4 in celery). A 21-hit
manual sample spread across all five corpora then classified 21 true positives
and 0 false positives, and it turned up five *byte-for-byte* duplicate tests
that are latent bugs rather than mere noise:

* one repo A site — a test named for a None-input edge case never sets that
  input up, so it is byte-for-byte its sibling happy-path test under a different
  name and asserts nothing about the path it is named for,
* a second repo A site — `test_superadmin_can_delete_any_record` is
  `test_delete_record` verbatim, with no superadmin actor anywhere in it,
* a third repo A site — a list round-trip test repeats an earlier round-trip
  test with the locals renamed, which is the case the local-name
  canonicalization exists to catch,
* `fastapi/tests/test_compat.py:118` — the "pipe union" variant of
  `test_serialize_sequence_value_with_optional_list` uses the same
  `list[str] | None` annotation as the test it is supposed to contrast with,
* `celery/t/unit/backends/test_base.py:1419` —
  `test_chord_part_return_propagate_default` is identical to
  `..._propagate_set`, so one of the two configures nothing.

fastapi's 18.6% is its suite being one-endpoint-per-test by construction
(`tests/test_path.py` alone holds a 31-member group of `client.get(path)` /
`assert status` / `assert json` bodies), and every cluster read there was a real,
collapsible table. An earlier draft of this docstring called that "a genuine
outlier rather than a rule defect"; that framing does not survive dogfooding.
Run against this repo's own suite the rule fires on **23.5%** of substantive
tests (125 of 533) — worse than the case being excused, and on a shape the
calibration corpus never contained: a lint-rule suite whose tests are entirely
literal-driven, where erasing every constant erases the whole specification and
a file of unrelated guards collapses into one group. Two narrowings were
proposed and are **not** implemented here — requiring the erased literals to be
short and single-line, or requiring at least one non-literal difference — both
of which need the 21/0 true-positive validation re-run before they could ship.
Until then the honest statement is that this rule is noisy on literal-driven
suites, not that fastapi is unusual.

Reporting is **one diagnostic per group**, placed on the group's first copy, not
one per copy. One first-party test module emitted eight diagnostics all naming
the same first copy as the original — eight findings for one `parametrize`
refactor, which reads as eight problems.

A group whose members are **byte-for-byte identical** gets a different message,
because there is no varying argument to lift into a `parametrize` column: the
action is to fix or delete one of them. Every such pair read across the corpora
was a copy-paste that never got its edit (see the five cited above).

Deliberately NOT flagged:

* **members whose documentation differs.** When two bodies are identical code
  and different prose — a docstring, or a comment inside the body — collapsing
  them forces one of the two texts to be deleted, and the text is routinely the
  only record of why the two exist. This rule shipped alongside **SARJ070
  `prefer-or-pattern`**, which suppresses on exactly this signal for `match`
  arms; the two took opposite positions on the same question until this guard
  was ported across, since an earlier design stripped the docstring before
  comparing. SARJ070's guard is measured on two independent sites — one
  first-party site where two `case` arms have identical bodies but differing
  trailing comments (`# 7 data points` / `# 30-31 data points`) and litellm's
  `user_api_key_auth_mcp.py:776` (`# Unreachable: kept for match exhaustiveness`)
  — and on this repo's own suite 29 of 125 findings paired tests whose differing
  documentation is provenance no `ids=` could carry: two different corpus
  citations (`tests/rules/test_over_mocked_test.py:788` and `:797`, one citing
  celery and one a first-party repo), or two regression pins naming the separate historical
  bugs they hold down (`packages/iac/tests/rules/test_require_deletion_protection.py:192`
  and `:286`). Identical documentation on both members still groups them,

* **`unittest.TestCase` methods.** pytest documents that
  `@pytest.mark.parametrize` cannot be applied to a `unittest.TestCase`
  subclass, so the fix this rule asks for is not available there and the
  diagnostic would be unactionable. The unittest answer — a table plus
  `with self.subTest(...)` — is a different transformation, and SARJ041 already
  treats `subTest` as an acceptable substitute for parametrize. This is the
  single largest guard by volume: it takes django's suite from **458 findings
  to 0**, every one of the 458 being a `TestCase` method where the advice would
  have been wrong — among them
  `django/tests/migrations/test_writer.py:346` (`test_serialize_multiline_strings`
  against `test_serialize_strings`, six literals apart and genuinely two
  scenarios), `django/tests/test_utils/tests.py:1264` and
  `django/tests/staticfiles_tests/test_storage.py:124`. Detected two ways,
  because django's suite needs both: a base class
  named like a test case (`TestCase`, `SimpleTestCase`, `TransactionTestCase`,
  and suite-local intermediates such as `ChoiceWidgetTest` in
  `django/tests/forms_tests/widget_tests/test_select.py:10`), or a body calling
  a TestCase-only `self.` API (`self.assertEqual`, `self.subTest`,
  `self.skipTest`) — which catches the mixin classes that carry test methods
  without inheriting a TestCase at all, such as django's `TestHashedFiles` in
  `staticfiles_tests/test_storage.py`,
* **functions in different classes**, even in the same module and with the same
  body. `class SQLiteTests(TestCase)` and `class PostgresTests(TestCase)` with
  the same three-line body are a deliberate parity pair whose behaviour comes
  from `setUp`, the class-level attributes, and the base class — none of which
  is visible in the body. django's backend suites are built entirely this way,
  and grouping across classes made them the single largest false-positive
  cluster. The container (module, or a specific class) is part of the identity,
* **functions whose decorators differ in any way**, compared verbatim with
  constants intact. Two bodies can be identical while
  `@pytest.mark.xfail(reason="ipv6 not supported")` versus
  `@pytest.mark.xfail(reason="ipv4 only")`, `@pytest.mark.skipif(sys.platform ==
  "win32")` versus a different condition, or `@override_settings(USE_TZ=True)`
  versus `USE_TZ=False` makes them genuinely different tests. The decorator *is*
  the parameter in those suites, and it is already spelled declaratively, so
  there is nothing to collapse,
* **a sync/async parity pair**. `def test_get` and `async def test_get_async`
  exercising the same assertions cover two different code paths in the library
  under test; a `parametrize` cannot merge them because pytest dispatches them
  differently. `async`-ness is part of the identity,
* **functions taking different parameters.** Fixtures are behaviour: `def
  test_x(client)` and `def test_x(async_client)` with the same body run against
  different systems. The parameter names are part of the identity,
* **short bodies.** A two-statement test is not evidence of copy-paste — call,
  assert, done, and any two tests of the same helper look alike. The 3-statement
  floor is what keeps the rule from firing on every well-factored unit suite,
* **generated test modules** (`_paths.is_generated`) — a generator emitting N
  near-identical cases is the generator's business, and the fix would be
  overwritten on the next regeneration,
* the **first** member of a group. The diagnostic goes on the copies and points
  back at the original, so a group of four reports three findings, not four.

## Implementation notes

### `_message`

A group whose members share every literal is not a `parametrize` candidate —
there is nothing to put in the table — so it gets its own message asking for
the copy to be fixed or deleted.

### `_bound_names`

Parameters are deliberately absent: they are only ever loaded in the body,
and their names are part of the function's identity rather than its shape.

### `_is_test_case_class`

A base the module defines is resolved and followed rather than pattern
matched, because the suite-local base is usually named for the *subject*
(`BaseAction`, `BaseTestChartDataApi`) while the TestCase it inherits from
sits a hop or two further up. The name test applies only to a base the
module does not define, where there is nothing left to follow.

### `_class_index`

Needed to follow a base class up its own inheritance chain: the name test
below is only meaningful on a base the module does *not* define.

### `_test_functions`

Only module-level functions and class methods are collected — a `test_*`
nested inside another function is a callback, not a test. The container tag
is `""` for the module body and the dotted class path otherwise, which is
what keeps two backend-parity classes from being compared against each other.

### `_erases_a_fixture_document`

Compares the group's constants position by position: a position where the
members disagree and at least one of them is a long multi-line string is a
whole embedded specification that normalization threw away, not a case value
a `parametrize` column could hold.

### `_documentation`

The span runs from the `def` line to the end of the body, so decorators —
already compared verbatim — are not counted twice.

### `_comment_lines`

Both halves come from `_comments`' single memoized tokenize pass, so this
costs nothing extra in a run where another comment rule already scanned the
file. A comment inside a string literal is *not* seen — which matters here,
because this rule's own suite embeds test programs containing `#` lines.

### `_duplicate_groups`

Raises out of here when `source` cannot be tokenized; `check` catches that.

### `_Canonicalizer`

Works on a deep copy: `parse_or_none` hands every rule the *same* module
object, so mutating a node in place would corrupt the tree for the rules
that run after this one.

### `_Shape`

`key` is equal for two functions of the same outline exactly when a
`parametrize` could merge them: the normalized body, plus the prose the two
functions carry. `literals` holds each erased constant in traversal order,
so two members of the same group have literal lists of the same length and
positional comparison names what differs.

### `_Outline`

One traversal, no copying and no `ast.dump` of the body: the identity fields
(container, async-ness, signature, decorators) plus the sequence of node
types the body contains. Two functions with different outlines can never
normalize to the same body, so the expensive `_Shape` pass only ever runs on
the functions whose outlines already collide — which in a normal module is
almost none of them.
