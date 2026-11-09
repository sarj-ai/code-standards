from __future__ import annotations

import ast


def plain_parameters(parameters: list[ast.type_param]) -> frozenset[str] | None:
    if any(
        not isinstance(item, ast.TypeVar) or item.bound is not None or item.default_value is not None
        for item in parameters
    ):
        return None
    return frozenset(item.name for item in parameters if isinstance(item, ast.TypeVar))


def record_parameters(node: ast.ClassDef) -> frozenset[str] | None:
    parameters = plain_parameters(node.type_params)
    if parameters is None or any(uses_parameters(item, parameters) for item in (*node.bases, *node.decorator_list)):
        return None
    return parameters


def specialized(expression: ast.expr, parameters: list[ast.type_param]) -> bool:
    if not parameters:
        return not isinstance(expression, ast.Subscript)
    if not isinstance(expression, ast.Subscript) or plain_parameters(parameters) is None:
        return False
    arguments = expression.slice.elts if isinstance(expression.slice, ast.Tuple) else [expression.slice]
    return len(arguments) == len(parameters) and not any(isinstance(item, ast.Starred) for item in arguments)


def uses_parameters(expression: ast.expr, parameters: frozenset[str]) -> bool:
    return bool(parameters) and any(
        isinstance(item, ast.Name) and item.id in parameters for item in ast.walk(expression)
    )
