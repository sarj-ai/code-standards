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
    Severity,
    is_suppressed,
)
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics, scope_bound_names
from sarj_python_lint.rules._ast_index import children, nodes, walk as walk_ast
from sarj_python_lint.rules._fixed_record import builds_fixed_record
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex
    from sarj_python_lint.rules._imports import ImportIndex


# Dict-conversion protocol methods: returning a raw dict is the declared
# contract (and inherited, for pydantic's `model_dump`/`dict`).
_DICT_CONVERSION_NAMES = frozenset({"asdict", "as_dict", "dict", "model_dump", "to_data", "to_dict"})
_DICT_CONVERSION_RE = re.compile(r"^(?:to|as)_[a-z0-9_]*(?:dict|data)$")
# `dict[K, V]` subscript carries exactly two type arguments.
_DICT_ARG_COUNT = 2
_DOCUMENTATION_DIR_NAMES = frozenset({"docs", "docs_src"})


class NamedRecordAtBoundaries(Rule):
    id: str = "named-record-at-boundaries"
    code: str = "SARJ008"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Public Python API returns an unnamed fixed-shape record.",
        rationale="A named record makes field types and required keys explicit to callers and static tooling.",
        remediation="Define and return a `TypedDict`, Pydantic model, or frozen dataclass for the fixed record shape.",
        category=RuleCategory.ARCHITECTURE,
        aliases=("pydantic-at-boundaries", "named-fixed-record-return"),
        limitations=(
            "Visible FastAPI routes are owned by SARJ094. Private functions and classes, closures, tests, generated files, documentation examples, recognized framework hooks, and dictionary conversion methods are excluded.",
            (
                "Record evidence is flow-sensitive but local: literals, proven built-in dict keyword construction, "
                "static string-key writes, and unique unconditional local type aliases are recognized. Dynamic keys, "
                "opaque escapes, ambiguous control flow, generic aliases, and cross-module aliases make the rule abstain."
            ),
        ),
        examples=(
            RuleExample(
                example_id="untyped-dictionary-boundary",
                title="Public API returns an unnamed record",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "service.py",
                        "def build_payload(call) -> dict[str, object]:\n    return {'id': call.id}\n",
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
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if is_test_path(path) or is_test_support_path(path) or context.generated or _is_documentation_path(path):
            return []
        tree = context.tree
        if tree is None:
            return []
        diags: list[Diagnostic] = []
        source_lines = context.source_lines
        local = _local_function_ids(tree)
        private_class_methods = _private_class_function_ids(tree)
        semantics = AnnotationSemantics.from_tree(tree)
        imports = semantics.imports
        fastapi = context.fastapi
        class_shadowed_annotations = _class_shadowed_annotation_ids(tree, semantics, node_index=context.node_index)

        def collect_boundary(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            if _is_overload(node, imports):
                return
            # Private/internal functions are not public boundaries — their
            # return shape is an implementation detail, not a data contract.
            if node.name.startswith("_"):
                return
            # A closure cannot be imported, so it is not a boundary either.
            if id(node) in local or id(node) in private_class_methods:
                return
            if id(node) in class_shadowed_annotations:
                return
            # `model_dump`/`asdict`/`to_dict`-style converters declare "this
            # returns a dict" as their contract — that is not a missing model.
            if _is_dict_conversion_name(node.name):
                return
            # Pydantic validator hooks (`@model_validator`/`@field_validator`)
            # take and return raw dict/values by contract — that's the API, not
            # a missing model.
            if _is_framework_hook(node, imports):
                return
            # SARJ094 owns visible routes. Hidden routes remain ordinary Python
            # APIs here unless FastAPI already has a concrete named model.
            routes = fastapi.routes(node)
            if any(not route.is_hidden for route in routes) or any(
                _has_named_response_model(route.keywords.get("response_model"), semantics) for route in routes
            ):
                return
            returns = semantics.parse(node.returns)
            if returns is None:
                return
            kind = _classify_return(returns, semantics)
            if (
                kind is None
                or not builds_fixed_record(node, imports=imports)
                or is_suppressed(source_lines, node.lineno, self.code)
            ):
                return
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

        for node in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            collect_boundary(node)
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


def _class_shadowed_annotation_ids(
    tree: ast.Module, semantics: AnnotationSemantics, *, node_index: NodeIndex | None = None
) -> set[int]:
    shadowed: set[int] = set()
    for class_node in nodes(tree, ast.ClassDef, index=node_index):
        bindings = scope_bound_names(class_node.body)
        for statement in class_node.body:
            if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            annotation = semantics.parse(statement.returns)
            if annotation is not None and any(
                isinstance(child, ast.Name) and child.id in bindings for child in walk_ast(annotation)
            ):
                shadowed.add(id(statement))
    return shadowed


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


def _classify_return(
    node: ast.expr,
    semantics: AnnotationSemantics,
    *,
    seen: frozenset[str] = frozenset(),
) -> str | None:
    imports = semantics.imports
    node = semantics.parse(node) or node
    if isinstance(node, ast.Name) and node.id in semantics.aliases:
        if node.id in seen:
            return None
        return _classify_return(semantics.aliases[node.id], semantics, seen=seen | {node.id})
    # Look through `X | None` / Optional[X] / Union[...] members.
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _classify_return(node.left, semantics, seen=seen) or _classify_return(node.right, semantics, seen=seen)

    if _is_type(node, imports, builtin="dict", typing_symbol="Dict"):
        return "dict"  # bare `dict` / `Dict`

    if not isinstance(node, ast.Subscript):
        return None

    return _classify_subscript_return(node, semantics, seen=seen)


def _classify_subscript_return(
    node: ast.Subscript,
    semantics: AnnotationSemantics,
    *,
    seen: frozenset[str],
) -> str | None:
    imports = semantics.imports

    if _is_typing_type(node.value, imports, "Annotated"):
        # Annotated carries its runtime value type in the first argument.
        return _classify_return(_first_type_argument(node.slice), semantics, seen=seen)
    if _is_typing_type(node.value, imports, "Optional"):
        return _classify_return(node.slice, semantics, seen=seen)
    if _is_typing_type(node.value, imports, "Union"):
        return _classify_union_return(node, semantics, seen=seen)
    if _is_type(node.value, imports, builtin="list", typing_symbol="List"):
        # Fixed lists of unnamed records need one named element contract.
        inner = _classify_return(node.slice, semantics, seen=seen)
        return "dict" if inner == "dict" else None
    if _is_type(node.value, imports, builtin="dict", typing_symbol="Dict"):
        return "dict" if _is_named_record_dict_args(node.slice, imports) else None
    # Heterogeneous tuple returns are NOT flagged — multiple return values are
    # idiomatic Python, not a missing data contract.
    return None


def _first_type_argument(node: ast.expr) -> ast.expr:
    if isinstance(node, ast.Tuple) and node.elts:
        return node.elts[0]
    return node


def _is_named_record_dict_args(slice_node: ast.expr, imports: ImportIndex) -> bool:
    if not isinstance(slice_node, ast.Tuple) or len(slice_node.elts) != _DICT_ARG_COUNT:
        return False
    key = _resolve_annotation(slice_node.elts[0])
    if key is None or not _is_builtin(key, imports, "str"):
        return False
    return _resolve_annotation(slice_node.elts[1]) is not None


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


def _has_named_response_model(node: ast.expr | None, semantics: AnnotationSemantics) -> bool:
    imports = semantics.imports
    resolved = _resolve_annotation(node)
    if resolved is None or (isinstance(resolved, ast.Constant) and resolved.value is None):
        return False
    if _classify_return(resolved, semantics) is not None:
        return False
    return not (_is_builtin(resolved, imports, "object") or _is_typing_type(resolved, imports, "Any"))


def _classify_union_return(
    node: ast.Subscript,
    semantics: AnnotationSemantics,
    *,
    seen: frozenset[str],
) -> str | None:
    if isinstance(node.slice, ast.Tuple):
        for elt in node.slice.elts:
            kind = _classify_return(elt, semantics, seen=seen)
            if kind is not None:
                return kind
        return None
    return _classify_return(node.slice, semantics, seen=seen)
