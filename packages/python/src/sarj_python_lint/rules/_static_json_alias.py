from __future__ import annotations

import ast
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics


_CONTAINERS = frozenset({"list", "dict", "tuple"})
_TYPING_CONTAINERS = frozenset({"List", "Dict", "Tuple", "Optional", "Union"})
_SCALARS = frozenset({"str", "int", "float", "bool", "None"})
_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_RUNTIME_ATTRIBUTES = frozenset({"__annotations__", "__value__", "get_type_hints", "TypeAdapter", "validate_call"})


def private_static_json_alias(tree: ast.Module, name: str, semantics: AnnotationSemantics) -> bool:
    if not name.startswith("_") or name.startswith("__"):
        return False
    nodes = tuple(ast.walk(tree))
    parents = {id(child): parent for parent in nodes for child in ast.iter_child_nodes(parent)}
    if any(_runtime_annotation_consumer(node, semantics) for node in nodes):
        return False
    safe: set[int] = set()
    for statement in tree.body:
        if (value := _alias_value(statement, name)) is not None:
            safe.update(id(node) for node in ast.walk(value))
    annotations = _private_annotations(tree, name, semantics, nodes, parents)
    if not annotations:
        return False
    safe.update(id(node) for annotation in annotations for node in ast.walk(annotation))
    return all(id(node) in safe for node in nodes if _references_name(node, name))


def _private_annotations(
    tree: ast.Module, name: str, semantics: AnnotationSemantics, nodes: tuple[ast.AST, ...], parents: dict[int, ast.AST]
) -> list[ast.expr]:
    annotations: list[ast.expr] = []
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not _function_stays_local(function, nodes, parents):
            continue
        annotations.extend(
            annotation
            for annotation in _function_annotations(function)
            if any(_references_name(node, name) for node in ast.walk(annotation))
            and _static_annotation(annotation, name, semantics)
        )
    return annotations


def _alias_value(statement: ast.stmt, name: str) -> ast.expr | None:
    match statement:
        case ast.TypeAlias(name=ast.Name(id=identifier), value=value) if identifier == name:
            return value
        case ast.AnnAssign(target=ast.Name(id=identifier), value=value) if identifier == name:
            return value
        case _:
            return None


def _references_name(node: ast.AST, name: str) -> bool:
    if isinstance(node, ast.Name):
        return isinstance(node.ctx, ast.Load) and node.id == name
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and name in node.value


def _function_stays_local(
    function: ast.FunctionDef | ast.AsyncFunctionDef, nodes: tuple[ast.AST, ...], parents: dict[int, ast.AST]
) -> bool:
    if not function.name.startswith("_") or function.name.startswith("__") or function.decorator_list:
        return False
    for node in nodes:
        if not _references_name(node, function.name):
            continue
        parent = parents.get(id(node))
        if not isinstance(node, ast.Name) or not isinstance(parent, ast.Call) or parent.func is not node:
            return False
    return True


def _function_annotations(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.expr]:
    arguments = function.args
    annotations = [
        argument.annotation
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
        if argument.annotation is not None
    ]
    if function.returns is not None:
        annotations.append(function.returns)
    return annotations


def _static_annotation(node: ast.expr, name: str, semantics: AnnotationSemantics, *, remaining: int = 64) -> bool:
    if remaining <= 0 or (parsed := semantics.parse(node)) is None:
        return False
    match parsed:
        case ast.Name(id=identifier):
            return identifier == name or (
                identifier in _SCALARS | _CONTAINERS and semantics.imports.builtin_is_unshadowed(identifier)
            )
        case ast.Constant(value=None):
            return True
        case ast.BinOp(left=left, op=ast.BitOr(), right=right):
            return _static_annotation(left, name, semantics, remaining=remaining - 1) and _static_annotation(
                right, name, semantics, remaining=remaining - 1
            )
        case ast.Subscript(value=value, slice=arguments):
            builtin = (
                isinstance(value, ast.Name)
                and value.id in _CONTAINERS
                and semantics.imports.builtin_is_unshadowed(value.id)
            )
            canonical = any(
                semantics.imports.resolves(value, sources=_TYPING_SOURCES, symbol=symbol)
                for symbol in _TYPING_CONTAINERS
            )
            return (builtin or canonical) and all(
                _static_annotation(argument, name, semantics, remaining=remaining - 1)
                for argument in (arguments.elts if isinstance(arguments, ast.Tuple) else [arguments])
            )
        case _:
            return False


def _runtime_annotation_consumer(node: ast.AST, semantics: AnnotationSemantics) -> bool:
    if isinstance(node, ast.Attribute) and node.attr in _RUNTIME_ATTRIBUTES:
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in _RUNTIME_ATTRIBUTES:
        return True
    if not isinstance(node, ast.Call):
        return False
    qualified = semantics.imports.resolved_qualified_name(node.func)
    return qualified in {
        "pydantic.TypeAdapter",
        "pydantic.type_adapter.TypeAdapter",
        "pydantic.validate_call",
        "typing.get_type_hints",
        "typing_extensions.get_type_hints",
    }
