# SARJ057 `no-tautological-expect` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_no_tautological_expect.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`assert True`, `assert ["..."]`, `self.assertEqual(1, 1)` — the condition
contains no value the code under test produced, so the assertion passes before
the program runs. It is not a weak test, it is a *non*-test: deleting the
function under test entirely would not change the result.

Two shapes dominate, and neither looks wrong at a glance:

* **the placeholder that was never replaced** — `expect(true).toBe(true)` in
  TypeScript, `assert True` in Python, left behind when a test file was
  scaffolded and the body never written;
* **the assertion whose real condition slid out of the condition slot.** This is
  the dangerous one, because it was a working assertion when it was typed. Home
  Assistant has the same six-line condition twice in
  `tests/helpers/test_device_registry.py` (:3711, :3777), wrapped in braces
  rather than parentheses::

      assert {
          "calls `device_registry.async_get_or_create` "
          "referencing a non existing `via_device` " in caplog.text
      }

  The braces make it a one-element **set display**, which is truthy whatever the
  `in` test inside it evaluates to. Airflow has the list-literal spelling in
  `providers/apache/hdfs/.../log/test_hdfs_task_handler.py:170`,
  `assert [f"No logs found on hdfs for ti={ti}"]`, where the `== messages` was
  lost. And Home Assistant's `emulated_hue/test_hue_api.py:1078` shows the third
  variant, where the value slid into the assertion-*message* slot:
  `assert True, cover_result_json[0]["success"][...]` — a `KeyError` there would
  still be raised, so it half-works, which is why it survived review.

Fires on exactly four shapes, all of them syntactically decidable:

1. `assert <always-truthy literal>` — `True`, a nonzero number (signed or not), a
   non-empty string, `not <falsy scalar constant>` (`not False`, `not 0`,
   `not ""`, `not None`), or a non-empty list/set/dict/tuple **display**;
2. `assert <literal> == <textually identical literal>` (and `is`);
3. `assertTrue(<truthy literal>)` / `assertFalse(<falsy literal>)`;
4. `assertEqual(<literal>, <textually identical literal>)` (and `assertIs`).

**Boundary with SARJ064 `trivially-true-assertion`.** This rule owns every
assertion whose fixed outcome is visible in the assertion syntax itself: bare
constants, `not <falsy constant>`, container displays, identical-literal
comparisons and the `unittest` assertion calls. SARJ064 starts where
cross-statement construction tracking is required — reading a constructor
keyword straight back out, or asserting that an object produced by calling a
class is an instance of that same class. The two rules used to overlap on bare
truthy constants and non-empty displays, which cost a doubled diagnostic on 42
positions across a 21-repository, 42,761-file census; SARJ064 ceded the shape
because this rule reaches further (production code, modules pytest never
collects, signed constants) and carries carve-outs SARJ064 lacked for the
`except`-handler marker and pytest-benchmark bodies.

**The narrowness is the rule.** The obvious generalisation — "flag a comparison
of a thing with itself" — was measured and is ~95% false positives.
`assert i == i`, `assert x is x`, `expect(hash([o])).toEqual(hash([o]))` are
*reflexivity, determinism and memoization* tests: for a type with a custom
`__eq__` or `__hash__`, `x == x` is precisely the property under test and can
genuinely fail. So an operand that is an identifier, an attribute or a call is
never enough; both sides must be literals, and textually identical ones.

Deliberately NOT flagged:

* **`assert True` as the sole statement of an `except` handler** — the
  deliberate "reaching here is the acceptable outcome" marker, the mirror image
  of the `assert False` that precedes it in the `try`. It reads as a tautology
  in isolation and is a real assertion in context: it asserts *which branch ran*.
  Both known Python false positives are this shape —
  `pydantic-core/tests/benchmarks/test_micro_benchmarks.py:716` and
  `core/tests/components/mqtt/test_client.py:1353`;
* **`assert <constant>` in a `match` arm when a sibling arm always fails** —
  the same reasoning as the `except` marker above, one construct along. In::

      match PROCESSOR.process(source_file=protected, password="not right"):
          case PDFProcessError(error=DecryptionError.INCORRECT_PASSWORD):
              assert True
          case _:
              raise AssertionError

  the *pattern* is the assertion: the test goes red the moment the result stops
  matching, so the marker records which arm ran rather than claiming a literal is
  true. Found against two sites in one first-party repo that was not in this
  rule's original 28,608-file corpus — so the "0 false
  positives" measured there held only because that repo was absent. A `match` with
  no failing arm proves nothing and still fires, as does a constant assertion
  outside the `match`;
* **anything inside a pytest-benchmark test**, whether it takes the `benchmark`
  fixture or wears `@pytest.mark.benchmark` — the same carve-out SARJ043 needs,
  shared through `_pytest.py`. The try/`assert False`/except/`assert True`
  sandwich above is the idiomatic way to time a *failing* validation path;
* `assert False` — the standard unreachable-branch marker, and an assertion that
  always fails is a loud problem, not a silent one;
* an empty container (`assert []`), which is always *falsy* — that is a failing
  assertion, again loud;
* a container display with a `*splat` or `**unpack` element (`assert [*items]`),
  whose emptiness depends on the runtime value;
* an f-string, whose truth depends on the interpolated values.

Measured before shipping: **4 findings across 28,608 files** — 26,346 of
pydantic, trio, attrs, Airflow and Home Assistant plus 2,262 first-party files
across five first-party repos. All 4 are the true positives
named above; 0 false positives. The `except`/benchmark carve-outs are
load-bearing rather than defensive: with `_exempt_nodes` neutered the sweep
gains exactly the two known false positives and nothing else.

Re-measured on the corpus this standard now tracks — 21 repositories and 42,761
files, seven first-party repos plus 14 OSS suites: **61 findings**, spread
litellm 29, django 8, dagster 7, prefect 7, sentry-python 3, celery 2,
superset 2, airflow 1, langchain 1, one first-party repo 1, and zero in the
other eleven. Taking over
`not <falsy scalar constant>` from SARJ064 added **0** findings to that total —
the shape is rare enough that nobody in 42,761 files writes it — so it is here as
a contract this rule now owns rather than as a source of volume.

## Implementation notes

### `_is_literal`

An identifier, attribute, call or f-string is not — its value comes from
somewhere the syntax cannot see, which is exactly what makes an assertion on
it a real assertion.

### `_is_identical_literal_comparison`

Single-operator comparisons only, and only `==`/`is`. Both operands must be
literals: `assert i == i` and `assert x is x` are reflexivity tests on a
real object and are the false positives this rule exists to avoid.

### `_nonempty_container_kind`

A `*splat`/`**unpack` element makes emptiness a runtime question, so those
are excluded — `assert [*items]` really can fail.

### `_constant_truth`

`not <falsy scalar constant>` is the spelling SARJ064 used to own; it arrived
here with the literal-only tautologies. A `not` on anything the syntax cannot
evaluate — a name, a call, a display — stays unknown, because `assert not x`
is an ordinary assertion.

### `_match_arm_markers`

The `except`-handler carve-out above generalises: when one arm of a `match`
always fails, a constant assertion in another arm is a statement about which
pattern matched, not about the literal. The pattern *is* the assertion, and
the test goes red the moment the subject stops matching it.

### `_exempt_nodes`

Every node under a pytest-benchmark test, plus the lone `assert` that forms
an `except` handler's whole body — the "this exception is the acceptable
outcome" marker, which is a statement about control flow rather than about a
literal.
