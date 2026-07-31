# SARJ042 `parametrize-case-needs-id` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_parametrize_case_needs_id.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

pytest derives a test id from each case value. For scalars that works — a case
of `("429", True)` reports as `test_retries[429-True]`, which names itself. For a
`dict`, a `set`, or a constructed object it cannot: pytest falls back to a
positional placeholder, so a failing case reports as `test_thing[payload0]`. The
CI log then says a test failed without saying which case, and the reader has to
count list elements in the source to find out. Worse, several such cases collide
into `payload0`, `payload1` in declaration order, so reordering the table
silently renames every test id.

Fires when ALL of these hold:

* the file is a test file, and the call sits **in a decorator list** and is
  `@pytest.mark.parametrize` (or a bare `parametrize` imported from pytest),
* the decorator does **not** pass `ids=` — one `ids=` covers the whole table, so
  its presence exempts every case,
* and **every** column of the case is opaque to pytest's id generation: a
  `dict`, `set`, comprehension, or a constructor/factory `Call`.

  Requiring *every* column, not any, is the difference between a useful rule and
  a noisy one. pytest builds an id by joining the per-argument ids with `-`, so a
  single nameable column still distinguishes the case: `("0.0", Decimal("0.0"))`
  reports as `0.0-value1`, which a reader can find. A third-party sweep over
  pydantic, flask, httpx, requests and rich flagged 372 tables under the
  any-column reading; the overwhelming majority paired an opaque value with a
  perfectly nameable string or number — `Decimal('0.0')`, `datetime(2012, 4, 9)`,
  `UUID(...)`, `timedelta(hours=10)`, `Err('...')` — and were false positives.
  Only a case whose columns are *all* opaque degenerates to `case0`, `case1`,
* and that specific case is not individually named by `pytest.param(..., id=...)`.

The `pytest.param` unwrap is the load-bearing false-positive guard. A first pass
that treated any `ast.Call` in the case list as opaque reported 135 hits and was
almost entirely wrong: `pytest.param(...)` is itself a `Call`, so every correctly
id'd case was flagged. Unwrapping the wrapper and reading its `id=` before
judging the payload cut the population to 57 real hits with no observed false
positives.

Deliberately NOT flagged:

* scalar cases — strings, numbers, booleans, `None`, and enum members all
  generate readable ids on their own,
* **a call to a builtin scalar constructor.** pytest's `_idval` renders the
  *runtime value*, so `float('nan')` reports as `nan`, `int(1e10)` as
  `10000000000`, and `type(None)` as `NoneType` (anything with a `__name__` is
  named by it). Treating every `Call` as opaque flagged 8 tables in the
  third-party sweep that name themselves perfectly:
  `pydantic/tests/test_validators.py:249` (`[float('nan'), float('inf')]`),
  `pydantic/tests/test_types.py:2823` and `:5267` (`(None, type(None))`),
  `pydantic/pydantic-core/tests/validators/test_int.py:34`, `:181`, `:248`,
  `.../test_float.py:74` and `.../test_decimal.py:178`. `str`, `bytes`, `int`,
  `float`, `bool`, `complex`, `type` and `re.compile` are the constructors
  pytest can always name; `dict(...)`, `Decimal(...)`, `datetime(...)` and every
  other factory still degenerate to `case0`,
* **a `parametrize(...)` call outside a decorator list.** `is_test_path` accepts
  everything under `tests/`, which sweeps in formatter fixtures:
  `black/tests/data/cases/split_delimiter_comments.py:14` and `:41` contain a
  top-level `parametrize(({}, {}), ({}, {}))` expression that is input data for
  black, not a pytest table. Requiring decorator position removed both,
* any table carrying a decorator-level `ids=`, whether a list or a callable,
* a case already wrapped in `pytest.param(..., id="...")`,
* `parametrize` whose values argument is a name or a call rather than an inline
  literal — the cases are not visible here, so nothing can be judged about them,
* an empty table.

## Implementation notes

### `_decorator_calls`

A `parametrize(...)` anywhere else is not applied to a test — in a formatter
fixture it is not even pytest's `parametrize`.
