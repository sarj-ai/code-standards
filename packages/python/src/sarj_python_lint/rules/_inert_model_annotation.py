from __future__ import annotations

import ast
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from sarj_python_lint.rules._imports import ImportIndex


_BUILTINS = frozenset({"bool", "bytes", "dict", "float", "frozenset", "int", "list", "object", "set", "str", "tuple"})
_QUALIFIED_BUILTINS = frozenset(f"builtins.{name}" for name in _BUILTINS)
_MAX_ANNOTATION_LENGTH = 4096
_CANONICAL_TYPES = frozenset(
    {
        "typing.Annotated",
        "typing.Any",
        "typing.ClassVar",
        "typing.Literal",
        "typing.Optional",
        "typing.Union",
        "typing_extensions.Annotated",
        "typing_extensions.ClassVar",
        "typing_extensions.Literal",
        "pydantic.PositiveInt",
        "pydantic.NonNegativeInt",
        "pydantic.types.PositiveInt",
        "pydantic.types.NonNegativeInt",
    }
)
_LITERAL_CONSTRAINTS = frozenset(
    {
        "pydantic.Field",
        "pydantic.fields.Field",
        "annotated_types.Ge",
        "annotated_types.Gt",
        "annotated_types.Le",
        "annotated_types.Lt",
        "annotated_types.MultipleOf",
    }
)


def inert_model_annotation(node: ast.expr, imports: ImportIndex, *, remaining: int = 64) -> bool:
    if remaining <= 0:
        return False
    match node:
        case ast.Constant(value=str() as source):
            if len(source) > _MAX_ANNOTATION_LENGTH:
                return False
            try:
                parsed = ast.parse(source, mode="eval").body
            except SyntaxError, ValueError, RecursionError:
                return False
            return inert_model_annotation(parsed, imports, remaining=remaining - 1)
        case ast.Constant(value=None):
            return True
        case ast.Name(id=name):
            return (name in _BUILTINS and imports.builtin_is_unshadowed(name)) or imports.resolved_qualified_name(
                node
            ) in _CANONICAL_TYPES
        case ast.Attribute():
            qualified = imports.resolved_qualified_name(node)
            return qualified in _CANONICAL_TYPES or qualified in _QUALIFIED_BUILTINS
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return inert_model_annotation(left, imports, remaining=remaining - 1) and inert_model_annotation(
                right, imports, remaining=remaining - 1
            )
        case ast.Subscript():
            return _subscript_annotation(node, imports, remaining=remaining)
        case _:
            return False


def _subscript_annotation(node: ast.Subscript, imports: ImportIndex, *, remaining: int) -> bool:
    if not inert_model_annotation(node.value, imports, remaining=remaining - 1):
        return False
    arguments = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    qualified = imports.resolved_qualified_name(node.value)
    if qualified in {"typing.Literal", "typing_extensions.Literal"}:
        return all(_literal(item) for item in arguments)
    if qualified in {"typing.Annotated", "typing_extensions.Annotated"}:
        return (
            bool(arguments)
            and inert_model_annotation(arguments[0], imports, remaining=remaining - 1)
            and all(_constraint(item, imports) for item in arguments[1:])
        )
    return all(inert_model_annotation(item, imports, remaining=remaining - 1) for item in arguments)


def _constraint(node: ast.expr, imports: ImportIndex) -> bool:
    if _literal(node):
        return True
    return (
        isinstance(node, ast.Call)
        and imports.resolved_qualified_name(node.func) in _LITERAL_CONSTRAINTS
        and all(_literal(argument) for argument in node.args)
        and all(keyword.arg is not None and _literal(keyword.value) for keyword in node.keywords)
    )


def _literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) or (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.UAdd | ast.USub)
        and isinstance(node.operand, ast.Constant)
        and isinstance(node.operand.value, int | float)
        and not isinstance(node.operand.value, bool)
    )


_MODEL_FIELD_SOURCES = frozenset({"pydantic", "pydantic.fields", "pydantic.v1", "pydantic.v1.fields"})


def inert_direct_model_body(cls: ast.ClassDef, imports: ImportIndex) -> bool:
    if cls.decorator_list or cls.keywords or cls.type_params or len(cls.bases) != 1:
        return False
    for statement in cls.body:
        match statement:
            case ast.Pass() | ast.Expr(value=ast.Constant(value=str())):
                continue
            case ast.AnnAssign(target=ast.Name(), annotation=annotation, value=value):
                if not inert_model_annotation(annotation, imports):
                    return False
                if value is None or isinstance(value, ast.Constant):
                    continue
                if (
                    isinstance(value, ast.Call)
                    and imports.resolves(value.func, sources=_MODEL_FIELD_SOURCES, symbol="Field")
                    and not value.args
                    and all(
                        keyword.arg is not None and _model_literal_value(keyword.value) is not None
                        for keyword in value.keywords
                    )
                ):
                    continue
                return False
            case _:
                return False
    return True


def _model_literal_value(node: ast.expr | None) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant):
        numeric = _model_numeric_value(node.operand.value)
        if numeric is not None:
            return -numeric
    return None


def _model_numeric_value(value: object) -> float | None:
    match value:
        case bool():
            return None
        case int() | float():
            return float(value)
        case _:
            return None
