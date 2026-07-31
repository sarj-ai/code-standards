# SARJ015 `prefer-struct-over-namedtuple` — evidence

Behaviour is specified by [the tests](../../packages/python/tests/rules/test_prefer_struct_over_namedtuple.py); every guard below
has a named test asserting it. This file holds what a test cannot carry: the
measurements that chose each threshold, and the false-positive family each
guard exists to stop.

`collections.namedtuple` produces an untyped, positionally-constructed tuple:
fields have no type annotations, the type checker can't catch a wrong-typed
field, and it silently supports tuple unpacking by position — the exact bug
class a named value object exists to prevent. `typing.NamedTuple` is the typed,
modern equivalent; a frozen pydantic `BaseModel` is better still when the value
crosses a boundary and needs validation.

    # flagged
    from collections import namedtuple
    Point = namedtuple("Point", ["x", "y"])
    Row = collections.namedtuple("Row", "id name")

    # preferred
    from typing import NamedTuple
    class Point(NamedTuple):
        x: float
        y: float

`typing.NamedTuple` is NOT flagged — it is the recommended form.

Test files are exempt (`_paths.is_test_path`): a `collections.namedtuple` in a
test is usually the *subject* — exercising code that must accept untyped
namedtuples (pydantic's validation tests were the sweep case) — not a value
object the test should model properly.

The famous-repo sweep (2,657 files of fastapi / pydantic / black / sqlmodel /
rich / flask / httpx / requests / anyio) produced exactly 2 hits and BOTH are
true positives, so no exemption was added:

- `httpx/httpx/_urls.py:409` — `RawURL = collections.namedtuple("RawURL",
  ["raw_scheme", "raw_host", "port", "raw_path"])`, built inside a deprecated
  `URL.raw` property. Four fields, no types, and the surrounding annotation is
  the positional `tuple[bytes, bytes, int, bytes]` this rule's sibling SARJ026
  flags; a `class RawURL(NamedTuple)` fixes both.
- `rich/rich/pretty.py:90` — `_dummy_namedtuple = collections.namedtuple(
  "_dummy_namedtuple", [])`, a probe used to locate the file of the generated
  `__repr__`. `class _DummyNamedTuple(NamedTuple): pass` produces the same
  generated `__repr__`, so the rewrite is available here too.

The rule stayed at 2 hits over 2,657 files: it is rare, precise, and cheap.

Suppress with `# sarj-noqa: SARJ015 — <reason>`.

References:
- https://docs.python.org/3/library/typing.html#typing.NamedTuple
