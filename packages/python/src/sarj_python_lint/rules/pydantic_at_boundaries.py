from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, override

from sarj_python_lint.rule_base import (
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_suppressed,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import children, nodes
from sarj_python_lint.rules._fastapi import FastapiIndex
from sarj_python_lint.rules._fixed_record import builds_fixed_record
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated, is_test_path, is_test_support_path


if TYPE_CHECKING:
    from pathlib import Path


# Dict-conversion protocol methods: returning a raw dict is the declared
# contract (and inherited, for pydantic's `model_dump`/`dict`).
_DICT_CONVERSION_NAMES = frozenset({"asdict", "as_dict", "dict", "model_dump", "to_data", "to_dict"})
_DICT_CONVERSION_RE = re.compile(r"^(?:to|as)_[a-z0-9_]*(?:dict|data)$")
# `dict[K, V]` subscript carries exactly two type arguments.
_DICT_ARG_COUNT = 2
_DOCUMENTATION_DIR_NAMES = frozenset({"docs", "docs_src"})


class PydanticAtBoundaries(Rule):
    id: str = "pydantic-at-boundaries"
    code: str = "SARJ008"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        summary="Public Python API returns an unnamed fixed-shape record.",
        rationale="A named record makes field types and required keys explicit to callers and static tooling.",
        remediation="Define and return a `TypedDict`, Pydantic model, or frozen dataclass for the fixed record shape.",
        category=RuleCategory.ARCHITECTURE,
        aliases=("named-fixed-record-return",),
        limitations=(
            "Visible FastAPI routes are owned by SARJ094. Private functions and classes, closures, tests, generated files, documentation examples, recognized framework hooks, and dictionary conversion methods are excluded.",
            "Only returned record literals and locally built fixed-shape dictionaries are recognized.",
        ),
        examples=(
            RuleExample(
                example_id="untyped-dictionary-boundary",
                title="Public API returns an unnamed record",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "from typing import Any\n\ndef build_payload(call) -> dict[str, Any]:\n    return {'id': call.id}\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-boundary-model",
                title="TypedDict names the returned record",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "from typing import TypedDict\n\nclass CallPayload(TypedDict):\n    id: str\n\ndef build_payload(call) -> CallPayload:\n    return {'id': call.id}\n",
                    ),
                ),
                focus_path=PurePosixPath("service.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description: str = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            is_test_path(path)
            or is_test_support_path(path)
            or is_generated(path, source)
            or _is_documentation_path(path)
        ):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        source_lines = source.splitlines()
        local = _local_function_ids(tree)
        private_class_methods = _private_class_function_ids(tree)
        imports = ImportIndex.from_tree(tree, module_scope_only=True)
        fastapi = FastapiIndex(tree, path=path)
        for node in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef):
            if _is_overload(node, imports):
                continue
            # Private/internal functions are not public boundaries — their
            # return shape is an implementation detail, not a data contract.
            if node.name.startswith("_"):
                continue
            # A closure cannot be imported, so it is not a boundary either.
            if id(node) in local or id(node) in private_class_methods:
                continue
            # `model_dump`/`asdict`/`to_dict`-style converters declare "this
            # returns a dict" as their contract — that is not a missing model.
            if _is_dict_conversion_name(node.name):
                continue
            # Pydantic validator hooks (`@model_validator`/`@field_validator`)
            # take and return raw dict/values by contract — that's the API, not
            # a missing model.
            if _is_framework_hook(node, imports):
                continue
            # SARJ094 owns visible routes. Hidden routes remain ordinary Python
            # APIs here unless FastAPI already has a concrete named model.
            routes = fastapi.routes(node)
            if any(not route.is_hidden for route in routes) or any(
                _has_named_response_model(route.keywords.get("response_model"), imports) for route in routes
            ):
                continue
            returns = _resolve_annotation(node.returns)
            if returns is None:
                continue
            kind = _classify_return(returns, imports)
            if kind is None or not builds_fixed_record(node) or is_suppressed(source_lines, node.lineno, self.code):
                continue
            ann_text = ast.unparse(returns)
            diags.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    message=(
                        f"`{node.name}` returns unnamed fixed record `{ann_text}` — define a "
                        "`TypedDict`, Pydantic model, or frozen dataclass for this shape."
                    ),
                )
            )
        return sorted(diags, key=lambda diagnostic: (diagnostic.line, diagnostic.col, diagnostic.message))


def _local_function_ids(tree: ast.Module) -> set[int]:
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


def _is_documentation_path(path: Path) -> bool:
    return any(part.lower() in _DOCUMENTATION_DIR_NAMES for part in path.parts)


def _is_dict_conversion_name(name: str) -> bool:
    return name in _DICT_CONVERSION_NAMES or _DICT_CONVERSION_RE.fullmatch(name) is not None


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> bool:
    for dec in node.decorator_list:
        if isinstance(dec, (ast.Name, ast.Attribute)) and _is_typing_type(dec, imports, "overload"):
            return True
    return False


_PYDANTIC_HOOKS = frozenset(
    {"field_serializer", "field_validator", "model_serializer", "model_validator", "root_validator", "validator"}
)


def _is_framework_hook(node: ast.FunctionDef | ast.AsyncFunctionDef, imports: ImportIndex) -> bool:
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if not isinstance(target, (ast.Name, ast.Attribute)):
            continue
        if any(imports.resolves(target, sources=frozenset({"pydantic"}), symbol=symbol) for symbol in _PYDANTIC_HOOKS):
            return True
        if imports.resolves(target, sources=frozenset({"pytest"}), symbol="fixture"):
            return True
        if imports.resolves(target, sources=frozenset({"marshmallow", "marshmallow.decorators"}), symbol="post_dump"):
            return True
        if imports.resolves(
            target,
            sources=frozenset({"typing", "typing_extensions"}),
            symbol="override",
        ):
            return True
    return False


def _private_class_function_ids(tree: ast.Module) -> set[int]:
    private: set[int] = set()

    def visit(node: ast.AST, *, inside_private_class: bool) -> None:
        if isinstance(node, ast.ClassDef):
            inside_private_class = inside_private_class or node.name.startswith("_")
        if inside_private_class and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            private.add(id(node))
        for child in children(node):
            visit(child, inside_private_class=inside_private_class)

    visit(tree, inside_private_class=False)
    return private


def _resolve_annotation(node: ast.expr | None) -> ast.expr | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return ast.parse(node.value.strip(), mode="eval").body
        except SyntaxError:
            return None
    return node


def _classify_return(node: ast.expr, imports: ImportIndex) -> str | None:
    # Look through `X | None` / Optional[X] / Union[...] members.
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _classify_return(node.left, imports) or _classify_return(node.right, imports)

    if _is_type(node, imports, builtin="dict", typing_symbol="Dict"):
        return "dict"  # bare `dict` / `Dict`

    if not isinstance(node, ast.Subscript):
        return None

    if _is_typing_type(node.value, imports, "Annotated"):
        # Annotated carries its runtime value type in the first argument.
        if isinstance(node.slice, ast.Tuple) and node.slice.elts:
            return _classify_return(node.slice.elts[0], imports)
        return _classify_return(node.slice, imports)
    if _is_typing_type(node.value, imports, "Optional"):
        return _classify_return(node.slice, imports)
    if _is_typing_type(node.value, imports, "Union"):
        if isinstance(node.slice, ast.Tuple):
            for elt in node.slice.elts:
                kind = _classify_return(elt, imports)
                if kind is not None:
                    return kind
            return None
        return _classify_return(node.slice, imports)
    if _is_type(node.value, imports, builtin="list", typing_symbol="List"):
        # Only list-of-untyped-dict is flagged (e.g. `list[dict[str, Any]]`).
        inner = _classify_return(node.slice, imports)
        return "dict" if inner == "dict" else None
    if _is_type(node.value, imports, builtin="dict", typing_symbol="Dict"):
        return "dict" if _is_untyped_dict_args(node.slice, imports) else None
    # Heterogeneous tuple returns are NOT flagged — multiple return values are
    # idiomatic Python, not a missing data contract.
    return None


def _is_untyped_dict_args(slice_node: ast.expr, imports: ImportIndex) -> bool:
    if not isinstance(slice_node, ast.Tuple) or len(slice_node.elts) != _DICT_ARG_COUNT:
        return False
    key = _resolve_annotation(slice_node.elts[0])
    if key is None or not _is_builtin(key, imports, "str"):
        return False
    value = _resolve_annotation(slice_node.elts[1])
    return value is not None and (_is_builtin(value, imports, "object") or _is_typing_type(value, imports, "Any"))


def _is_type(node: ast.expr, imports: ImportIndex, *, builtin: str, typing_symbol: str) -> bool:
    return _is_builtin(node, imports, builtin) or _is_typing_type(node, imports, typing_symbol)


def _is_builtin(node: ast.expr, imports: ImportIndex, name: str) -> bool:
    return (isinstance(node, ast.Name) and node.id == name and imports.builtin_is_unshadowed(name)) or imports.resolves(
        node, sources=frozenset({"builtins"}), symbol=name
    )


def _is_typing_type(node: ast.expr, imports: ImportIndex, symbol: str) -> bool:
    return imports.resolves(
        node,
        sources=frozenset({"typing", "typing_extensions"}),
        symbol=symbol,
    )


def _has_named_response_model(node: ast.expr | None, imports: ImportIndex) -> bool:
    resolved = _resolve_annotation(node)
    if resolved is None or (isinstance(resolved, ast.Constant) and resolved.value is None):
        return False
    if _classify_return(resolved, imports) is not None:
        return False
    return not (_is_builtin(resolved, imports, "object") or _is_typing_type(resolved, imports, "Any"))
