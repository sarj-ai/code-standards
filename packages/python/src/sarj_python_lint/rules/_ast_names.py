from __future__ import annotations

import ast


def root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def expression_root(node: ast.expr) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def terminal_name(node: ast.expr) -> str | None:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return None


def unqualified_name(node: ast.expr) -> str:
    match node:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return ""


def dotted_parts(node: ast.expr) -> tuple[str, ...] | None:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return None
    parts.append(current.id)
    return tuple(reversed(parts))


def dotted_name(node: ast.expr) -> str | None:
    parts = dotted_parts(node)
    return ".".join(parts) if parts is not None else None


def assignment_names(node: ast.AST) -> set[str]:
    match node:
        case ast.Name(id=name):
            return {name}
        case ast.Tuple() | ast.List():
            names: set[str] = set()
            for element in node.elts:
                names.update(assignment_names(element))
            return names
        case ast.Starred(value=value):
            return assignment_names(value)
        case _:
            return set()
