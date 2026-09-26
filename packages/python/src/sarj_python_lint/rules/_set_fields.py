from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._imports import ImportIndex


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._project_index import ClassSummary, ProjectIndexSet, SourceUnit


def declared_set_fields(
    function: ast.FunctionDef | ast.AsyncFunctionDef, project: ProjectIndexSet, context: PythonFileContext
) -> set[str]:
    changed = _changed_roots(function)
    fields: set[str] = set()
    for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs):
        if argument.arg in changed or argument.annotation is None:
            continue
        summary = _field_class(argument.annotation, project, context)
        if summary is None:
            continue
        owner = project.source_unit(summary.symbol.module)
        if owner is None or owner.tree is None:
            continue
        for name, annotation in summary.fields.items():
            if _builtin_set_annotation(annotation, owner) and _plain_field(owner, summary.symbol.name, name):
                fields.add(f"{argument.arg}.{name}")
    return fields


def _field_class(annotation: ast.expr, project: ProjectIndexSet, context: PythonFileContext) -> ClassSummary | None:
    root = annotation
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name) or any(
        node.id == root.id and isinstance(node.ctx, (ast.Store, ast.Del)) for node in context.nodes(ast.Name)
    ):
        return None
    qualified = context.module_imports.resolved_qualified_name(annotation)
    unit = project.unit(context.path)
    if qualified is not None:
        module, _, name = qualified.rpartition(".")
        unit = project.source_unit(module)
        annotation = ast.Name(id=name, ctx=ast.Load())
    return project.class_for(unit, annotation) if unit is not None else None


def _builtin_set_annotation(annotation: ast.expr, unit: SourceUnit) -> bool:
    if unit.tree is None:
        return False
    base = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    return (
        isinstance(base, ast.Name)
        and base.id in {"set", "frozenset"}
        and ImportIndex.from_tree(unit.tree, module_scope_only=True).builtin_is_unshadowed(base.id)
    )


def _plain_field(unit: SourceUnit, class_name: str, name: str) -> bool:
    if unit.tree is None:
        return False
    owner = next((node for node in unit.tree.body if isinstance(node, ast.ClassDef) and node.name == class_name), None)
    if owner is None:
        return False
    for statement in owner.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name in {
            name,
            "__getattribute__",
            "__getattr__",
        }:
            return False
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in {name, "set", "frozenset"} for target in statement.targets
        ):
            return False
    return True


def _changed_roots(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    changed: set[str] = set()
    for node in (node for statement in function.body for node in walk_ast(statement)):
        match node:
            case ast.Name(id=name, ctx=ast.Store() | ast.Del()):
                changed.add(name)
            case ast.Attribute(ctx=ast.Store() | ast.Del()):
                root = node.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name):
                    changed.add(root.id)
            case ast.Import(names=aliases) | ast.ImportFrom(names=aliases):
                changed.update(alias.asname or alias.name.split(".")[0] for alias in aliases)
            case (
                ast.ExceptHandler(name=str(name))
                | ast.MatchAs(name=str(name))
                | ast.MatchStar(name=str(name))
                | ast.MatchMapping(rest=str(name))
                | ast.arg(arg=name)
                | ast.FunctionDef(name=name)
                | ast.AsyncFunctionDef(name=name)
                | ast.ClassDef(name=name)
            ):
                changed.add(name)
            case _:
                pass
    return changed
