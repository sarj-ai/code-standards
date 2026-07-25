"""SARJ008: untyped dict / heterogeneous tuple at a function boundary — use pydantic.

The anti-pattern:

    def build_payload(call: Call) -> dict[str, Any]:
        return {"id": call.id, "status": call.status}

    async def stop_call(...) -> tuple[bool, str | None]:
        ...

    @router.get("/calls/{call_id}")
    async def get_call(call_id: str):   # no return annotation at all
        ...

Raw ``dict[str, Any]`` / ``dict[str, object]`` / bare ``dict`` returns and
heterogeneous ``tuple[...]`` returns hide the shape of the data from both the
type checker and the reader. Define a pydantic model (or frozen dataclass)
instead — Python analogue of ``@sarj/prefer-schema-for-api-payload``:

    class CallPayload(BaseModel):
        id: CallId
        status: CallStatus

    def build_payload(call: Call) -> CallPayload: ...

Purely annotation-based (no type inference), checked on function definitions
(sync + async):

1. Return annotation that is ``dict[str, Any]`` / ``dict[str, object]`` /
   bare ``dict`` / ``Dict``, or ``list[dict[str, Any]]``.
2. FastAPI route handlers (``@router.get(...)`` / ``@app.post(...)`` etc.)
   with no return annotation and no ``response_model=`` in the decorator.

Deliberately NOT flagged (kept high-precision for real boundaries):
private / ``_``-prefixed functions (internal, not a public contract), pydantic
``@model_validator`` / ``@field_validator`` hooks (raw dict in/out is their
API), ``tuple[...]`` returns (multiple return values are idiomatic Python),
fully-concrete dict value types (``dict[str, str]``), ``@overload`` stubs, and
test files.

References:
- https://docs.pydantic.dev/latest/concepts/models/
- https://fastapi.tiangolo.com/tutorial/response-model/

"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from sarj_python_lint.rule_base import Diagnostic, Rule, parse_or_none


if TYPE_CHECKING:
    from pathlib import Path


_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
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
    """Untyped dict return at a public boundary — define a pydantic model."""

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
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _is_overload(node):
                continue
            # Private/internal functions are not public boundaries — their
            # return shape is an implementation detail, not a data contract.
            if node.name.startswith("_"):
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
                if route is not None and not route.has_response_model:
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=node.lineno,
                            col=node.col_offset + 1,
                            code=self.code,
                            message=(
                                f"FastAPI route `{node.name}` has no return "
                                "annotation — declare a pydantic response model "
                                "(or pass `response_model=`)."
                            ),
                        )
                    )
                continue
            kind = _classify_return(returns)
            if kind is None:
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


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in node.decorator_list:
        if isinstance(dec, ast.Name) and dec.id == "overload":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "overload":
            return True
    return False


_VALIDATOR_DECORATORS = {"model_validator", "field_validator", "validator", "root_validator"}


def _is_validator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether `node` is a pydantic validator hook.

    Its dict/value in-and-out is a required contract, so the rule exempts it.

    Returns:
        True when the function carries a pydantic validator decorator.

    """
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = _flat_name(target) if isinstance(target, (ast.Name, ast.Attribute)) else ""
        if name in _VALIDATOR_DECORATORS:
            return True
    return False


def _is_fixture(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Report whether `node` is a pytest fixture (`@pytest.fixture` / `@fixture`).

    Returns:
        True when the function carries a fixture decorator.

    """
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = _flat_name(target) if isinstance(target, (ast.Name, ast.Attribute)) else ""
        if name == "fixture":
            return True
    return False


def _route_info(node: ast.FunctionDef | ast.AsyncFunctionDef) -> _RouteInfo | None:
    """Detect a FastAPI route decorator: `@<router|app|*_router>.<method>(...)`.

    Returns:
        The route info, or None when no route decorator is present.

    """
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
    """Unwrap a string forward-reference annotation into its parsed expression.

    Returns:
        The parsed expression, or None on a syntax error; `node` unchanged otherwise.

    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return ast.parse(node.value.strip(), mode="eval").body
        except SyntaxError:
            return None
    return node


def _classify_return(node: ast.expr) -> str | None:
    """Classify the annotation as a flagged shape.

    Returns:
        "dict" / "tuple" if the annotation is a flagged shape, else None.

    """
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
    """Report whether `dict[K, V]` is flagged (`str` keys with `Any`/`object` values).

    Only a str-keyed dict is a record shape a pydantic model can replace. A dict
    keyed by anything else (`dict[TypeVar, Any]`, `dict[type, Any]`) is a
    mapping — a data structure, not an unnamed record (pydantic's own
    `typevars_map` helpers were the sweep case).

    Returns:
        True when the dict is a str-keyed record shape with untyped values.

    """
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
