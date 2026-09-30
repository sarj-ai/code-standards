from __future__ import annotations

import ast


def annotation_reference(annotation: ast.expr) -> ast.Name | ast.Attribute | None:
    match annotation:
        case ast.Name() | ast.Attribute():
            return annotation
        case ast.Constant(value=str() as value):
            try:
                return annotation_reference(ast.parse(value, mode="eval").body)
            except SyntaxError, ValueError:
                return None
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            if isinstance(left, ast.Constant) and left.value is None:
                return annotation_reference(right)
            if isinstance(right, ast.Constant) and right.value is None:
                return annotation_reference(left)
        case ast.Subscript(value=value, slice=inner):
            if (wrapped := _nullable_inner(value, inner)) is not None:
                return annotation_reference(wrapped)
        case _:
            return None
    return None


def _nullable_inner(wrapper: ast.expr, inner: ast.expr) -> ast.expr | None:
    name = _tail(wrapper)
    if name == "Optional":
        return inner
    if name == "Annotated" and isinstance(inner, ast.Tuple) and inner.elts:
        return inner.elts[0]
    if name != "Union" or not isinstance(inner, ast.Tuple):
        return None
    substantive = [item for item in inner.elts if not isinstance(item, ast.Constant) or item.value is not None]
    return substantive[0] if len(substantive) == 1 else None


def _tail(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None
