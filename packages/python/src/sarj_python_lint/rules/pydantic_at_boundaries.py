"""SARJ008 — An ad-hoc dict record at a function boundary — use pydantic.

Examples: https://github.com/sarj-ai/standards/blob/main/packages/python/tests/rules/test_pydantic_at_boundaries.py
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none
from sarj_python_lint.rules._ast_index import children, nodes


if TYPE_CHECKING:
    from pathlib import Path


_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
# Dict-conversion protocol methods: returning a raw dict is the declared
# contract (and inherited, for pydantic's `model_dump`/`dict`).
_DICT_CONVERSION_NAMES = {"asdict", "as_dict", "dict", "model_dump", "to_data", "to_dict"}
_DICT_NAMES = {"dict", "Dict"}
_LIST_NAMES = {"list", "List"}
_ANY_VALUE_NAMES = {"Any", "object"}
# `dict[K, V]` subscript carries exactly two type arguments.
_DICT_ARG_COUNT = 2


@dataclass(frozen=True, slots=True)
class _RouteInfo:
    """A FastAPI route decorator found on a function."""

    has_response_model: bool


class PydanticAtBoundaries(Rule):
    id: str = "pydantic-at-boundaries"
    code: str = "SARJ008"
    description: str = "Public function/route returns an untyped dict — define a pydantic model (or frozen dataclass)."

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if _is_test_path(path):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        local = _local_function_ids(tree)
        for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef):
            if _is_overload(node):
                continue
            # Private/internal functions are not public boundaries — their
            # return shape is an implementation detail, not a data contract.
            if node.name.startswith("_"):
                continue
            # A closure cannot be imported, so it is not a boundary either.
            if id(node) in local:
                continue
            # `model_dump`/`asdict`/`to_dict`-style converters declare "this
            # returns a dict" as their contract — that is not a missing model.
            if node.name in _DICT_CONVERSION_NAMES:
                continue
            # Pydantic validator hooks (`@model_validator`/`@field_validator`)
            # take and return raw dict/values by contract — that's the API, not
            # a missing model.
            if _is_validator(node):
                continue
            # A `@pytest.fixture` is test scaffolding, not a public data
            # contract — its return shape is an implementation detail.
            if _is_fixture(node):
                continue
            route = _route_info(node)
            returns = _resolve_annotation(node.returns)
            if returns is None:
                # Only an ad-hoc record built in place is an unnamed model. A
                # mapping the function merely parses/forwards/reflects over has
                # no declarable shape. Checked last: it walks the body.
                if route is not None and not route.has_response_model and _builds_record_literal(node):
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=node.lineno,
                            col=node.col_offset + 1,
                            code=self.code,
                            message=(
                                f"FastAPI route `{node.name}` returns an ad-hoc "
                                "dict with no return annotation — declare a "
                                "pydantic response model (or pass "
                                "`response_model=`)."
                            ),
                        )
                    )
                continue
            kind = _classify_return(returns)
            if kind is None or not _builds_record_literal(node):
                continue
            ann_text = ast.unparse(returns)
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"`{node.name}` returns `{ann_text}` — define a "
                        "pydantic model (or frozen dataclass) for this shape."
                    ),
                )
            )
        return diags


def _is_test_path(path: Path) -> bool:
    return path.name.startswith("test_") or "tests" in path.parts


def _local_function_ids(tree: ast.Module) -> set[int]:
    """Collect `id()`s of every function defined inside another function's body."""
    out: set[int] = set()
    stack: list[tuple[ast.AST, bool]] = [(tree, False)]
    while stack:
        node, inside = stack.pop()
        for child in children(node):
            child_is_func = isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            if child_is_func and inside:
                out.add(id(child))
            stack.append((child, inside or child_is_func))
    return out


def _is_record_literal(node: ast.expr) -> bool:
    """Report whether `node` is an unnamed record built in place."""
    if isinstance(node, ast.List):
        return any(_is_record_literal(elt) for elt in node.elts)
    if isinstance(node, ast.ListComp):
        return _is_record_literal(node.elt)
    if not isinstance(node, ast.Dict):
        return False
    return any(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in node.keys)


def _builds_record_literal(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether the function returns a record it built in place."""
    returned: list[ast.expr] = []
    record_names: set[str] = set()
    stack: list[ast.AST] = list(node.body)
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(current, ast.Return) and current.value is not None:
            returned.append(current.value)
        elif isinstance(current, ast.Assign) and _is_record_literal(current.value):
            record_names.update(t.id for t in current.targets if isinstance(t, ast.Name))
        elif (
            isinstance(current, ast.AnnAssign)
            and isinstance(current.target, ast.Name)
            and current.value is not None
            and _is_record_literal(current.value)
        ):
            record_names.add(current.target.id)
        stack.extend(children(current))
    return any(
        _is_record_literal(value) or (isinstance(value, ast.Name) and value.id in record_names) for value in returned
    )


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "overload":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "overload":
            return True
    return False


_VALIDATOR_DECORATORS = {"model_validator", "field_validator", "validator", "root_validator"}


def _is_validator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether `node` is a pydantic validator hook."""
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = _flat_name(target) if isinstance(target, (ast.Name, ast.Attribute)) else ""
        if name in _VALIDATOR_DECORATORS:
            return True
    return False


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether `node` is a pytest fixture (`@pytest.fixture` / `@fixture`)."""
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = _flat_name(target) if isinstance(target, (ast.Name, ast.Attribute)) else ""
        if name == "fixture":
            return True
    return False


def _route_info(node: ast.FunctionDef | ast.AsyncFunctionDef) -> _RouteInfo | None:
    """Detect a FastAPI route decorator: `@<router|app|*_router>.<method>(...)`."""
    for dec in node.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        func = dec.func
        if not isinstance(func, ast.Attribute) or func.attr not in _HTTP_METHODS:
            continue
        receiver = func.value
        if not isinstance(receiver, ast.Name):
            continue
        name = receiver.id
        if name in {"app", "router"} or name.endswith("_router"):
            has_response_model = any(kw.arg == "response_model" for kw in dec.keywords)
            return _RouteInfo(has_response_model=has_response_model)
    return None


def _resolve_annotation(node: ast.expr | None) -> ast.expr | None:
    """Unwrap a string forward-reference annotation into its parsed expression."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return ast.parse(node.value.strip(), mode="eval").body
        except SyntaxError:
            return None
    return node


def _classify_return(node: ast.expr) -> str | None:
    """Classify the annotation as a flagged shape."""
    # Look through `X | None` / Optional[X] / Union[...] members.
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _classify_return(node.left) or _classify_return(node.right)

    name = _flat_name(node)
    if name in _DICT_NAMES:
        return "dict"  # bare `dict` / `Dict`

    if not isinstance(node, ast.Subscript):
        return None

    base = _flat_name(node.value)
    if base == "Annotated":
        # `Annotated[T, ...]` carries the real type as its first argument
        # (common in FastAPI). Classify T, ignore the metadata.
        if isinstance(node.slice, ast.Tuple) and node.slice.elts:
            return _classify_return(node.slice.elts[0])
        return _classify_return(node.slice)
    if base == "Optional":
        return _classify_return(node.slice)
    if base == "Union":
        if isinstance(node.slice, ast.Tuple):
            for elt in node.slice.elts:
                kind = _classify_return(elt)
                if kind is not None:
                    return kind
            return None
        return _classify_return(node.slice)
    if base in _LIST_NAMES:
        # Only list-of-untyped-dict is flagged (e.g. `list[dict[str, Any]]`).
        inner = _classify_return(node.slice)
        return "dict" if inner == "dict" else None
    if base in _DICT_NAMES:
        return "dict" if _is_untyped_dict_args(node.slice) else None
    # Heterogeneous tuple returns are NOT flagged — multiple return values are
    # idiomatic Python, not a missing data contract.
    return None


def _is_untyped_dict_args(slice_node: ast.expr) -> bool:
    """Report whether `dict[K, V]` is flagged (`str` keys with `Any`/`object` values)."""
    if not isinstance(slice_node, ast.Tuple) or len(slice_node.elts) != _DICT_ARG_COUNT:
        return False
    key = _resolve_annotation(slice_node.elts[0])
    if key is None or _flat_name(key) != "str":
        return False
    value = _resolve_annotation(slice_node.elts[1])
    return value is not None and _flat_name(value) in _ANY_VALUE_NAMES


def _flat_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr  # `typing.Dict` -> `Dict`
    return ""
