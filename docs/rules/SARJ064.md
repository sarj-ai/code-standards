# SARJ064 `trivially-true-assertion` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_trivially_true_assertion.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

A test earns its keep by being able to go red. An assertion whose truth is
settled by the test's own source text cannot, so it adds a line to the coverage
report and nothing to the suite. The dominant real-world spelling is not
`assert True` — it is reading a constructor's keyword argument straight back
out::

    payload = EncryptedPayload(
        operation_key_id="key-123",
        jws_signature="sig-456",
        encrypted_payload="encrypted-data",
    )

    assert payload.operation_key_id == "key-123"
    assert payload.jws_signature == "sig-456"

Nothing in those three lines can fail unless pydantic stops assigning fields.
The test is named `test_encrypted_payload_fields` (one first-party
authentication test) and it verifies the
language, not the model.

**Boundary with SARJ057 `no-tautological-expect`.** Literal-only tautologies are
deliberately left to SARJ057: bare truthy constants, `not <falsy constant>`,
non-empty container displays, identical-literal comparisons and the `unittest`
assertion calls. This rule only reports the tautologies that require linking an
assertion to an earlier construction — the constructor-keyword echo and
`isinstance`-after-construction, neither of which SARJ057 models at all.

The two rules used to share the constant shape, and a census over 21
repositories and 42,761 files priced the redundancy exactly: SARJ064 reported
726, SARJ057 reported 61, and 42 of those were the *same* assertion at the same
`line:col` — 69% of everything SARJ057 said. Ceding runs in this direction, not
the other, because SARJ057 is strictly the stronger owner of the syntax: it
carries carve-outs this rule never had for the sole-`assert` `except`-handler
marker and for pytest-benchmark bodies (constructed, this rule emitted on all
three and SARJ057 correctly stayed silent), it reads signed constants
(`assert -1`), and it runs in production code and in test-like modules pytest
never collects, where this rule deliberately does not look. Dropping the arm cost
**0 uniquely detected sites**: every one of the 42 remains reported, at the same
position, by SARJ057.

**What ruff already owns, and is therefore NOT duplicated here.** Every shape
below was checked against `ruff --select ALL --preview`, the configuration this
standard ships:

* `assert x == x`, `assert m is m` — PLR0124 (`comparison-with-itself`). This is
  the brief's "self-comparison of a mock" shape in full; it was implemented,
  found to be a straight duplicate, and **dropped**. It stays dropped: the one
  self-comparison bug in the whole estate is one first-party site's
  `case Error(error=error): assert error == error`
  in an IBAN-validation test, where the capture pattern
  shadows the `parametrize` argument and the whole `BAD_IBANS` table therefore
  verifies nothing — and PLR0124 was run against that file and does report it,
* `assert "a" in ["a", "b"]` — PLR6201 (`literal-membership`) fires on it, and
  an implementation of the always-true membership check found **zero**
  occurrences across all five corpora, so it too was **dropped**.

What survives is what neither ruff nor SARJ057 has a rule for: the two shapes
that need to see what the test constructed a line earlier.

Fires when either of these holds:

* a local name is bound exactly once to `SomeClass(..., field=<literal>)` and
  the test then asserts `name.field == <structurally identical literal>` (or
  `is`, the house spelling for a boolean field),
* a local name is bound exactly once to `SomeClass(...)` and the test then
  asserts `isinstance(name, SomeClass)`.

**One diagnostic per test function.** A test that echoes six constructor keywords
has one defect, not six, and every line of it is repaired by the same decision.
Reporting each assertion puts 1,283 diagnostics on the same 684 test functions,
so 47% of the estate-wide finding set would be a repeat line inside a test already
flagged. The rule reports the *first* unfalsifiable assertion in each function and
stays quiet about the rest, which loses no test. Note that this is a weaker
collapse than also requiring every assertion in the test to be trivial: that was
measured and costs 6 of repo A's 12 findings and 1 of repo C's 2, because
the common real shape is one honest assertion surrounded by echoes.

**The advice is conditioned on SARJ043.** 362 of the 684 findings are tests in
which *every* assertion is unfalsifiable, so acting on "drop the assertion" would
produce a test with no assertions at all — which SARJ043 (`zero-assertion-test`)
then rejects. Two rules in one suite must not give contradictory instructions, so
the message detects that case and asks for the behaviour the test name claims, or
for the test's deletion, instead of for a deletion of the line.

Corpus evidence — 21 repositories, 42,761 files: seven first-party repos
(repos A through G, labels stable within this docstring only) and 14 OSS suites.
**684 findings**, of which the
keyword echo carries 674 and `isinstance` 10: airflow 173, litellm 159,
superset 145, mlflow 70, prefect 67, langchain 28, dagster 21, repo A 12,
celery 3, repo B 3, repo C 2, sentry-python 1, and zero in django,
fastapi, saleor, zulip, warehouse, repo D, repo E, repo F and repo G. django's
suite is `unittest`-style (70 bare asserts in 2,927 files), so zero there is
arithmetic, not silence; fastapi's 4,828 bare asserts are almost all about an
HTTP response the test did not construct, and zero findings on that population
is the strongest evidence the shape is targeted. An external audit re-derived
the false-positive rate over 40,336 OSS files and measured ~9%, against the
7.1% originally claimed from five corpora — the only rule in this wave whose
claimed rate held at scale. That audit measured the rule with its constant arm
still attached; the 42 findings the arm contributed were every one of them a
duplicate of an SARJ057 diagnostic at the same position, so ceding them moved no
false positive and lost no site.

Deliberately NOT flagged:

* **anything but a class constructor.** The keyword-echo shape was originally
  written for any call, and 12 of the first 49 findings — a quarter — were
  functions whose *job* is to map their arguments onto a result, where the
  pass-through is exactly the behaviour under test: four first-party sites —
  `make_settings(monkeypatch, ENV="staging", ...)` then
  `assert settings.ENV == "staging"`, which reads an environment variable back
  through pydantic-settings;
  `service.get_onboarding_error_details(limit=25, offset=5)` then
  `assert result.limit == 25`, which checks a service echoes pagination into its
  response envelope;
  `collector.get_analytics(duration_ms=1234)`; and
  `factory.create_client(language="ar")` — plus celery's
  `event.get_exchange(conn, name='custom')`
  (`t/unit/events/test_events.py:540`), and two more first-party sites,
  `_worker_options(...)` and `create_global_variables(...)`.
  Only a callee whose final name
  component is capitalised — `Foo(...)`, `mod.Foo(...)`, `self.Backend(...)` —
  is treated as a constructor,
* **collaborator classes**, whose `__init__` normalises the configuration it is
  handed. celery's cache backends take `expires=` and run it through
  `prepare_expires`, so `CacheBackend(backend='memory://', expires=10)` then
  `assert tb.expires == 10` is a real coercion test named `test_expires_as_int`
  (`t/unit/backends/test_cache.py:126`, and the same shape at
  `test_couchbase.py:130` and `test_redis.py:1172`). A class whose name ends in
  `Backend`, `Client`, `Service`, `Store` and the like is a thing that does work,
  not a record that holds fields. `Receiver` joined that list on the same
  evidence: celery's `Receiver(Mock(), accept={'app/foo'})` then
  `assert r.accept == {'app/foo'}` (`t/unit/events/test_events.py:349`) coerces
  through `prepare_accept_content`. Measured across all 21 corpora the suffix
  removes exactly that one finding and no other,
* **a field the same module proves is transformed.** One first-party
  `GeminiLLMSettings` rewrites `model="lite"` to `"flash-lite-3.1"`; three
  functions down, `test_valid_model_unchanged` constructs it with
  `model="flash"` and asserts `settings.model == "flash"`. That assertion *can*
  fail —
  it is the negative half of a validator test — and only the sibling test four
  lines up reveals it. So when any construction of the same class in the same
  module asserts a field against a literal **different** from the one it was
  given, that class's field is known to coerce and every finding on it is
  dropped. The guard also clears celery's `CouchbaseBackend(expires=None)` then
  `assert b.expires == 10`,
* **dunder attributes.** `Proxy(real, __doc__='foo')` then
  `assert x.__doc__ == 'foo'` (celery `t/unit/utils/test_local.py:31`) is a real
  test: a lazy proxy resolving `__doc__` goes through descriptor machinery, not
  plain assignment,
* **an `isinstance` assertion that narrows for a later one.** basedpyright
  strict needs `assert isinstance(x, T)` to prove the assertions after it are
  well-typed; deleting it breaks the build. Any later assertion in the same
  function that mentions the name suppresses the finding, which is why celery's
  `test_from_message` (`t/unit/worker/test_request.py:1525`) is silent while
  `test_from_message_empty_args` twelve lines down, whose body is a construction
  and a bare `isinstance`, is not,
* **anything that touches the local between construction and assertion.** The
  name must be bound exactly once, must not be a parameter or declared
  `global`/`nonlocal`, and every read of it must be an attribute access inside
  an `assert`. Passing it to a function, calling a method on it, or simply
  reading it into another variable all disqualify it, because the object may no
  longer hold what the constructor was given,
* **a literal that changed shape.** Structural identity, not runtime equality:
  `Model(count=0)` then `assert m.count is False` compares equal at runtime but
  asserts a conversion, and `Email("A@B.com")` then
  `assert e.value == "a@b.com"` tests coercion. Neither fires. Nor does a
  differing attribute name — a pydantic alias or a derived field
  (`Model(name="A B")` then `assert m.slug == "a-b"`) — nor a round trip through
  serialisation (`assert Model(**d).model_dump() == d`), which binds no name at
  all,
* **a module pytest never collects.** `is_test_path` accepts everything under
  `tests/`; black keeps formatter fixtures in `tests/data/cases/` whose content
  is arbitrary Python, and `scripts/test_*.py` holds manual CLI probes.

Known residual false positives, both one finding each and both `# sarj-noqa:
SARJ064` material:

* celery's `Bunch(foo='foo', bar=2)` then `assert x.foo == 'foo'`
  (`t/unit/utils/test_objects.py:8`). `Bunch` is a kwargs-to-attributes bag, so
  storing keyword arguments *is* its whole behaviour and the tautology is the
  test. No syntactic signal distinguishes it from the models above,
* litellm's `DeleteContainerFileResponse(object="container.file.deleted")` then
  `assert m.object == "container.file.deleted"`
  (`tests/test_litellm/containers/test_container_utils.py:258`), whose sibling
  test does the same with `"container_file.deleted"`. Together the two assert
  that a pydantic model accepts both wire spellings, so the construction is the
  assertion. The obvious guard — suppress a `(class, field)` echoed with two or
  more *different* literals in one module — was implemented and measured: it
  removes 149 of the 733 findings, including 3 of repo A's 12, to buy this one
  false positive. **Rejected**; the shape is far too common among genuine
  echoes to trade on.

## Implementation notes

### `_narrows_for_a_later_assertion`

`assert isinstance(x, T)` ahead of real assertions on `x` is the idiom a
strict type checker requires to prove the later reads are well-typed.
Removing it breaks the build, so it is never a finding.

### `_is_isinstance_echo`

The class expression must be the callee itself: `x = Foo.build()` then
`assert isinstance(x, Foo)` checks what a factory returns, which is real.

### `_is_pure_literal`

Structural identity of two such literals, rather than runtime equality, is
what makes the echo check safe: `0` and `False` compare equal but a test
writing one and reading back the other asserts a conversion.

### `_kwarg_echo`

The result records whether the two literals match; a mismatch is the
evidence that `C.field` coerces, which suppresses the matches elsewhere.

### `_constructor_name`

A lowercase callee is a function, and a function that maps its arguments
onto a result is doing the work the test is there to check.

### `_constructed_locals`

Any other mention of the name — a rebind, a `del`, being passed to a
function, having a method called on it, or simply being read outside an
assertion — disqualifies it, because the object may no longer hold what the
constructor was given.

### `_construction_findings`

Resolved module-wide rather than per function, because a sibling test is
what reveals that a field coerces.

### `_index_module`

The perf gate is per rule, so the parent links, the per-function assertion
lists and the name bookkeeping all come out of a single descent rather than
three `ast.walk` passes.

Names are attributed to the **outermost** enclosing function, never the
nested one. A closure that mentions a local therefore still disqualifies it,
which is the conservative direction.

### `_one_per_test`

A test that echoes six constructor keywords has one defect, not six, and the
repair is the same line of thinking for all of them. Reporting each of them
made 45% of the estate-wide finding set repeat lines inside a test that was
already flagged.
