"""SARJ042 — An opaque parametrize case with no id reports as `test_x[case0]`.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_parametrize_case_needs_id.py
Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/SARJ042.md
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
    id: str = "parametrize-case-needs-id"
    code: str = "SARJ042"
    has_evidence: bool = True
    description: str = "Opaque `parametrize` case with no `ids=`/`id=` — the failing case reports as `case0`."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        """Flag parametrize cases whose value cannot produce a readable pytest id."""
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
    """Collect every call used as a decorator, in source order."""
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
