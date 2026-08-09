"""SARJ042 — An opaque parametrize case with no id reports as `test_x[case0]`.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_opaque_parametrize_case_needs_id.py
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    parse_or_none,
)
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


class OpaqueParametrizeCaseNeedsId(Rule):
    id: str = "opaque-parametrize-case-needs-id"
    code: str = "SARJ042"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Opaque `parametrize` case with no `ids=`/`id=` — the failing case reports as `case0`.",
        rationale="Generated case numbers are hard to diagnose and silently change when the parameter table is reordered.",
        remediation="Add `ids=` to the decorator or give each opaque `pytest.param` an explicit `id=`.",
        category=RuleCategory.TESTING,
        aliases=("parametrize-case-needs-id",),
        limitations=(
            "Only static list or tuple parameter tables in test files are analyzed.",
            "Cases with a pytest-readable scalar column or an explicit ID are allowed.",
        ),
        examples=(
            RuleExample(
                example_id="opaque-cases-without-ids",
                title="Dictionary cases receive generated names",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_handler.py",
                        'import pytest\n\n@pytest.mark.parametrize("payload", [{"a": 1}, {"a": 2}])\ndef test_handler(payload):\n    assert handle(payload)\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_handler.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="opaque-cases-with-ids",
                title="Dictionary cases have stable names",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "tests/test_handler.py",
                        'import pytest\n\n@pytest.mark.parametrize("payload", [{"a": 1}, {"a": 2}], ids=["first", "second"])\ndef test_handler(payload):\n    assert handle(payload)\n',
                    ),
                ),
                focus_path=PurePosixPath("tests/test_handler.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

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
        width = _parametrize_width(node.args[0])
        if width is None:
            continue
        count = sum(1 for case in values.elts if _is_unnameable(case, width))
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


def _has_keyword(node: ast.Call, name: str) -> bool:
    return any(kw.arg == name for kw in node.keywords)


def _parametrize_width(argnames: ast.expr) -> int | None:
    """Return the statically known number of parameters in a table."""
    if isinstance(argnames, ast.Constant) and isinstance(argnames.value, str):
        names = [stripped_name for name in argnames.value.split(",") if (stripped_name := name.strip())]
        return len(names) or None
    if isinstance(argnames, (ast.List, ast.Tuple)):
        if not argnames.elts or not all(
            isinstance(elt, ast.Constant) and isinstance(elt.value, str) for elt in argnames.elts
        ):
            return None
        return len(argnames.elts)
    return None


def _is_unnameable(case: ast.expr, width: int) -> bool:
    if isinstance(case, ast.Call) and _is_param_wrapper(case.func):
        # An explicitly named case is fine however opaque its payload is.
        if _has_keyword(case, "id"):
            return False
        if not case.args:
            return False
        if width == 1:
            return len(case.args) == 1 and _is_opaque_value(case.args[0], single_value=True)
        return all(_is_opaque_value(arg, single_value=True) for arg in case.args)
    if width == 1:
        return _is_opaque_value(case, single_value=True)
    if not isinstance(case, (ast.Tuple, ast.List)):
        return False
    return bool(case.elts) and all(_is_opaque_value(elt, single_value=True) for elt in case.elts)


def _is_param_wrapper(func: ast.expr) -> bool:
    if isinstance(func, ast.Attribute):
        return func.attr == _PARAM
    return isinstance(func, ast.Name) and func.id == _PARAM


def _is_opaque_value(value: ast.expr, *, single_value: bool) -> bool:
    # A multi-column case is a tuple. pytest joins the per-column ids with `-`,
    # so one nameable column is enough to tell the case apart — only an
    # all-opaque case degenerates to `case0`.
    if single_value and isinstance(value, (ast.Tuple, ast.List)):
        return True
    if isinstance(value, ast.Call) and _builds_a_nameable_value(value.func):
        return False
    return isinstance(value, _OPAQUE_NODES)


def _builds_a_nameable_value(func: ast.expr) -> bool:
    # `float('nan')` -> `nan`, `type(None)` -> `NoneType`: pytest renders the
    # value these produce, so the case names itself after all.
    if isinstance(func, ast.Attribute):
        return func.attr in _NAMEABLE_CONSTRUCTORS
    return isinstance(func, ast.Name) and func.id in _NAMEABLE_CONSTRUCTORS
