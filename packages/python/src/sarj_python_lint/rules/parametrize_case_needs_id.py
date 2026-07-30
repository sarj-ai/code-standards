"""SARJ042: an opaque parametrize case with no id reports as `test_x[case0]`.

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
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import nodes
from sarj_python_lint.rules._paths import is_test_path


if TYPE_CHECKING:
    from pathlib import Path


_PARAMETRIZE = "parametrize"

_PARAM = "param"

# Node kinds pytest cannot render into a readable test id.
_OPAQUE_NODES = (ast.Dict, ast.Set, ast.DictComp, ast.SetComp, ast.ListComp, ast.GeneratorExp, ast.Call)

# Constructors whose result pytest's `_idval` always renders: the scalar types
# it stringifies, plus `type` and `re.compile`, whose results carry a `__name__`
# / a `.pattern` that pytest reads instead.
_NAMEABLE_CONSTRUCTORS = frozenset({"str", "bytes", "int", "float", "bool", "complex", "type", "compile"})

_VALUES_ARG_INDEX = 1

_DECORATED_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


class ParametrizeCaseNeedsId(Rule):
    """An opaque `parametrize` case with no `id` reports as `case0` on failure."""

    id: str = "parametrize-case-needs-id"
    code: str = "SARJ042"
    description: str = "Opaque `parametrize` case with no `ids=`/`id=` — the failing case reports as `case0`."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag parametrize cases whose value cannot produce a readable pytest id.

        Returns:
            One diagnostic per unnameable case, sorted by position.

        """
        if not is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []

        diags = [
            Diagnostic(
                path=path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                message=(
                    f"{count} of this table's cases are dicts/sets/objects, which pytest cannot name — "
                    "they report as `case0`, `case1` and silently renumber if the table is reordered. "
                    'Add `ids=[...]` to the decorator, or wrap each case in `pytest.param(..., id="...")`.'
                ),
            )
            for node, count in _tables_with_unnameable_cases(tree)
        ]
        diags.sort(key=lambda d: (d.line, d.col))
        return diags


def _tables_with_unnameable_cases(tree: ast.Module) -> list[tuple[ast.Call, int]]:
    # One diagnostic per table, not per case: a single `ids=` on the decorator
    # resolves every case at once, so per-case reporting would be N copies of
    # one fix and would bury a large table's other diagnostics.
    hits: list[tuple[ast.Call, int]] = []
    for node in _decorator_calls(tree):
        if not _is_parametrize(node.func):
            continue
        if _has_keyword(node, "ids") or len(node.args) <= _VALUES_ARG_INDEX:
            continue
        values = node.args[_VALUES_ARG_INDEX]
        if not isinstance(values, (ast.List, ast.Tuple)):
            continue
        count = sum(1 for case in values.elts if _is_unnameable(case))
        if count:
            hits.append((node, count))
    return hits


def _decorator_calls(tree: ast.Module) -> list[ast.Call]:
    """Collect every call used as a decorator, in source order.

    A `parametrize(...)` anywhere else is not applied to a test — in a formatter
    fixture it is not even pytest's `parametrize`.

    Returns:
        The decorator calls of every function, method and class in the module.

    """
    return [dec for node in nodes(tree, *_DECORATED_NODES) for dec in node.decorator_list if isinstance(dec, ast.Call)]


def _is_parametrize(func: ast.expr) -> bool:
    # `@pytest.mark.parametrize(...)` or a bare `parametrize(...)` re-export.
    if isinstance(func, ast.Attribute):
        return func.attr == _PARAMETRIZE
    return isinstance(func, ast.Name) and func.id == _PARAMETRIZE


def _is_param_wrapper(func: ast.expr) -> bool:
    if isinstance(func, ast.Attribute):
        return func.attr == _PARAM
    return isinstance(func, ast.Name) and func.id == _PARAM


def _has_keyword(node: ast.Call, name: str) -> bool:
    return any(kw.arg == name for kw in node.keywords)


def _is_unnameable(case: ast.expr) -> bool:
    if isinstance(case, ast.Call) and _is_param_wrapper(case.func):
        # An explicitly named case is fine however opaque its payload is.
        if _has_keyword(case, "id"):
            return False
        return bool(case.args) and all(_is_opaque_value(arg) for arg in case.args)
    return _is_opaque_value(case)


def _is_opaque_value(value: ast.expr) -> bool:
    # A multi-column case is a tuple. pytest joins the per-column ids with `-`,
    # so one nameable column is enough to tell the case apart — only an
    # all-opaque case degenerates to `case0`.
    if isinstance(value, ast.Tuple):
        return bool(value.elts) and all(_is_opaque_value(elt) for elt in value.elts)
    if isinstance(value, ast.Call) and _builds_a_nameable_value(value.func):
        return False
    return isinstance(value, _OPAQUE_NODES)


def _builds_a_nameable_value(func: ast.expr) -> bool:
    # `float('nan')` -> `nan`, `type(None)` -> `NoneType`: pytest renders the
    # value these produce, so the case names itself after all.
    if isinstance(func, ast.Attribute):
        return func.attr in _NAMEABLE_CONSTRUCTORS
    return isinstance(func, ast.Name) and func.id in _NAMEABLE_CONSTRUCTORS
