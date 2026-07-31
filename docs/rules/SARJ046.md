# SARJ046 `xfail-requires-strict` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_xfail_requires_strict.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`@pytest.mark.xfail(reason="BUG: returns 404 instead of the error envelope")`
pins a known defect: the test asserts the *correct* behaviour and is expected to
fail until someone fixes it. Without `strict=True`, the day the bug is fixed the
test XPASSes — which pytest reports as a pass. Nobody is told, the marker stays
forever, and the test silently stops guarding anything. With `strict=True` an
XPASS is a hard failure that says "the bug is fixed, delete this marker", which
is the entire value of the pin.

Both audited repos already invented this convention independently — one has
a family of `test_known_*_bugs_xfail.py` modules whose docstrings spell out the
strict contract, and 45 of 52 `xfail` markers across the two repos already pass
`strict=True`. This rule locks in a practice the codebase chose, rather than
importing an outside opinion.

Fires when ALL of these hold:

* the file is a test file, and the decorator is `@pytest.mark.xfail(...)`,
* the marker carries a `reason=` naming a defect — the reason text matches
  `bug`, `broken`, `regression`, `should`, or `incorrect`,
* and `strict=` is absent or literally `False`.

**Exempting genuinely nondeterministic markers is not optional.** Of the five
non-strict `xfail`s found in that repo, all five sit on `@pytest.mark.real_llm`
evals whose reasons say "intermittently" — a live model that answers differently
run to run legitimately cannot be strict, and forcing it would make CI flake on
every provider drift. A rule without this guard would have been 100% wrong on
that population. Any marker on the same function naming a nondeterministic
source (`real_llm`, `flaky`, `network`) suppresses the diagnostic, as does a
reason mentioning intermittence.

Deliberately NOT flagged:

* **property-based and fuzz tests.** A `@given(...)` (hypothesis) or
  `<schema>.parametrize()` (schemathesis) decorator means one test function
  expands into many generated cases, and a documented bug is typically tripped
  by only a subset of them — the rest legitimately XPASS. `strict=True` there
  turns every passing generated input into a failure, which is why these suites
  set `strict=False` deliberately. Found against the other first-party repo's
  `test_calls_fuzz_known_bugs`, where the unroutable-id shapes trip the bug and
  the other generated ids do not,
* `xfail` with no `reason=`, or a reason describing an environment gate rather
  than a defect ("no GPU on CI") — those are not bug pins,
* **environment-gated conditional `xfail`.** A positional condition that probes
  the interpreter or OS — `@pytest.mark.xfail(platform.python_implementation()
  == "PyPy" and sys.pypy_version_info < (7, 3, 2), reason="PyPy has a bug in
  its incremental UTF-8 decoder")` — pins a *third-party* defect on the subset
  of environments that carry it, which is the same environment gate the bullet
  above excludes, merely spelled as code instead of prose. The reason text
  still says "bug", so the reason heuristic alone fired on it: 2 of the 5
  findings in a 2,657-file third-party sweep were this shape (anyio's
  `test_text.py`, pydantic-core's `test_complex.py`). Making those strict turns
  the day upstream ships the fix into a red build in an environment the project
  does not control. An *unconditional* `xfail` pinning our own defect still
  fires,
* `pytest.xfail(...)` called imperatively inside a body — that aborts the test
  immediately and has no strict/non-strict distinction,
* `xfail` used as a `pytest.param` marker argument, where the surrounding
  decorator context is not visible.

## Implementation notes

### `_is_environment_gated`

A conditional `xfail` whose condition probes `sys` / `platform` / `os` (or
names a version / implementation) applies the marker only on the
environments that carry a *third-party* defect. That is an environment gate,
not a pin on this codebase's own bug.
