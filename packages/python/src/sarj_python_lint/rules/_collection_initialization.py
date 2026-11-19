from __future__ import annotations

import ast
from itertools import starmap
from typing import TYPE_CHECKING

from sarj_python_lint._file_context import PythonFileContext
from sarj_python_lint.rules._declared_contracts import DeclaredClass
from sarj_python_lint.rules._local_source import unshadowed_import_namespace


if TYPE_CHECKING:
    from sarj_python_lint.rules._declared_contracts import DeclaredContracts

_CUSTOM_CONSTRUCTION = frozenset({"__init__", "__new__", "__setattr__"})


def collection_initializers(context: PythonFileContext) -> dict[ast.Assign, ast.Call]:
    candidates: dict[ast.Assign, ast.Call] = {}
    for function in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
        for creation, following in zip(function.body, function.body[1:], strict=False):
            assignment = _adjacent_initialization(creation, following, context)
            if assignment is not None and isinstance(creation, ast.Assign) and isinstance(creation.value, ast.Call):
                candidates[assignment] = creation.value
    return candidates


def _adjacent_initialization(creation: ast.stmt, following: ast.stmt, context: PythonFileContext) -> ast.Assign | None:
    if (
        not isinstance(creation, ast.Assign)
        or len(creation.targets) != 1
        or not isinstance(creation.targets[0], ast.Name)
    ):
        return None
    if (
        not isinstance(creation.value, ast.Call)
        or creation.value.args
        or any(item.arg is None for item in creation.value.keywords)
    ):
        return None
    assignment = _literal_assignment(following, context)
    if assignment is None or not isinstance(assignment.targets[0], ast.Attribute):
        return None
    receiver = assignment.targets[0].value
    if not isinstance(receiver, ast.Name) or receiver.id != creation.targets[0].id:
        return None
    if creation.targets[0].id in context.static_resource_provenance.external_bindings:
        return None
    return assignment


def _literal_assignment(node: ast.stmt, context: PythonFileContext) -> ast.Assign | None:
    guard = node if isinstance(node, ast.If) else None
    if guard is not None:
        if guard.orelse or len(guard.body) != 1 or not isinstance(guard.test, ast.Name):
            return None
        node = guard.body[0]
    if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Attribute):
        return None
    if not isinstance(node.value, ast.List) or not all(isinstance(item, ast.Constant) for item in node.value.elts):
        return None
    if guard is not None and isinstance(guard.test, ast.Name):
        binding = context.static_resource_provenance.binding(guard.test.id, guard.test)
        if (
            not isinstance(binding, ast.arg)
            or not isinstance(binding.annotation, ast.Name)
            or binding.annotation.id != "bool"
        ):
            return None
        if guard.test.id in context.static_resource_provenance.mutated:
            return None
        if (
            not context.static_resource_provenance.builtin_namespace_untouched
            or context.static_resource_provenance.binding("bool", binding.annotation) is not None
        ):
            return None
    return node


def constructor_collection_field(call: ast.Call, assignment: ast.Assign, contracts: DeclaredContracts) -> bool:
    context = contracts.context
    if contracts.unit is None or not isinstance(assignment.targets[0], ast.Attribute):
        return False
    model = _constructed_model(call, contracts)
    if model is None:
        return False
    source = (
        context
        if model.unit.path == context.path
        else PythonFileContext(model.unit.path, model.unit.source, context.session)
    )
    if source.tree is None:
        return False
    declarations = [
        node for node in source.tree.body if isinstance(node, ast.ClassDef) and node.name == model.declaration.name
    ]
    if len(declarations) != 1:
        return False
    model = DeclaredClass(model.unit, declarations[0])
    field = assignment.targets[0].attr
    if any(keyword.arg == field for keyword in call.keywords) or not _native_dataclass(model, source):
        return False
    fields = [
        node
        for node in model.declaration.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == field
    ]
    if len(fields) != 1 or source.binding_inventory.bindings.get(model.declaration, {}).get(field) != (
        fields[0].target,
    ):
        return False
    return _list_field(fields[0], source) and not _hook_reads_field(model.declaration, field)


def _constructed_model(call: ast.Call, contracts: DeclaredContracts) -> DeclaredClass | None:
    context = contracts.context
    if contracts.unit is None:
        return None
    root = call.func.value if isinstance(call.func, ast.Attribute) else call.func
    if not isinstance(root, ast.Name) or root.id in context.static_resource_provenance.mutated:
        return None
    binding = context.static_resource_provenance.binding(root.id, call)
    if not isinstance(binding, ast.alias | ast.ClassDef):
        return None
    if (
        isinstance(call.func, ast.Name)
        and isinstance(binding, ast.ClassDef)
        and context.parents.get(binding) is context.tree
    ):
        return DeclaredClass(contracts.unit, binding)
    summary = contracts.project.class_for(contracts.unit, call.func)
    unit = contracts.project.source_unit(summary.symbol.module) if summary is not None else None
    if unit is None or unit.tree is None or summary is None:
        return None
    classes = [node for node in unit.tree.body if isinstance(node, ast.ClassDef) and node.name == summary.symbol.name]
    if len(classes) != 1:
        return None
    return DeclaredClass(unit, classes[0])


def _native_dataclass(model: DeclaredClass, context: PythonFileContext) -> bool:
    cls = model.declaration
    if cls.bases or cls.keywords or cls.type_params or len(cls.decorator_list) != 1:
        return False
    provenance = context.static_resource_provenance
    if cls.name in provenance.mutated | provenance.external_bindings:
        return False
    if provenance.wildcard or provenance.dynamic_namespace or provenance.mock_namespace_patching:
        return False
    if not unshadowed_import_namespace(context.path, "dataclasses", facts=context.session.first_party):
        return False
    decorator = cls.decorator_list[0]
    head = decorator.func if isinstance(decorator, ast.Call) else decorator
    if provenance.runtime_import_name(head) != "dataclasses.dataclass":
        return False
    if isinstance(decorator, ast.Call) and (
        decorator.args
        or any(
            item.arg != "slots" or not isinstance(item.value, ast.Constant) or not isinstance(item.value.value, bool)
            for item in decorator.keywords
        )
    ):
        return False
    return not any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in _CUSTOM_CONSTRUCTION
        for node in cls.body
    )


def _list_field(field: ast.AnnAssign, context: PythonFileContext) -> bool:
    annotation = field.annotation
    if (
        not isinstance(annotation, ast.Subscript)
        or not isinstance(annotation.value, ast.Name)
        or annotation.value.id != "list"
    ):
        return False
    provenance = context.static_resource_provenance
    if not provenance.builtin_namespace_untouched or provenance.binding("list", annotation) is not None:
        return False
    value = field.value
    if not isinstance(value, ast.Call) or value.args:
        return False
    if provenance.runtime_import_name(value.func) != "dataclasses.field":
        return False
    options = {keyword.arg: keyword.value for keyword in value.keywords}
    if len(options) != len(value.keywords):
        return False
    factory = options.pop("default_factory", None)
    return (
        isinstance(factory, ast.Name)
        and factory.id == "list"
        and provenance.binding("list", factory) is None
        and all(starmap(_constructor_field_option, options.items()))
    )


def _constructor_field_option(name: str | None, value: ast.expr) -> bool:
    if not isinstance(value, ast.Constant):
        return False
    if name == "init":
        return value.value is True
    if name in {"repr", "compare", "kw_only"}:
        return isinstance(value.value, bool)
    return name == "hash" and (value.value is None or isinstance(value.value, bool))


def _hook_reads_field(cls: ast.ClassDef, field: str) -> bool:
    for method in cls.body:
        if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef) or method.name != "__post_init__":
            continue
        parameters = [*method.args.posonlyargs, *method.args.args]
        if not parameters:
            return True
        if any(
            isinstance(node, ast.Attribute)
            and node.attr == field
            and isinstance(node.value, ast.Name)
            and node.value.id == parameters[0].arg
            for node in ast.walk(method)
        ):
            return True
    return False
