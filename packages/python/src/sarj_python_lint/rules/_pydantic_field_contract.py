from __future__ import annotations

import ast
from collections import Counter
from functools import lru_cache
import tomllib
from typing import TYPE_CHECKING, TypeIs

from packaging.requirements import InvalidRequirement, Requirement
from packaging.version import InvalidVersion, Version

from sarj_python_lint.json_boundary import is_object_mapping
from sarj_python_lint.rules._annotation_origins import type_parameter_shadow
from sarj_python_lint.rules._first_party import distribution_root
from sarj_python_lint.rules._namespace_access import dynamic_namespace_access
from sarj_python_lint.rules._native_namespace_capability import native_namespace_capability_escapes


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance


MODEL_SOURCES = frozenset({"pydantic", "pydantic.main"})
SETTINGS_SOURCES = frozenset({"pydantic_settings", "pydantic_settings.main"})
FIELD_SOURCES = frozenset({"pydantic", "pydantic.fields"})
DECORATOR_SOURCES = frozenset({"pydantic", "pydantic.functional_validators", "pydantic.functional_serializers"})
TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_ALIAS_VERSION = Version("2.11")
_BUILTIN_BINDINGS = frozenset({"int", "float", "str", "list", "classmethod", "staticmethod"})
_GENERIC_BUILTINS = frozenset({"dict", "frozenset", "list", "set", "tuple", "type"})
_BUILTIN_SOURCES = frozenset({"builtins"})
_SENSITIVE_MODULES = frozenset({"pydantic", "typing", "typing_extensions", "builtins"})


def required_default_sentinel(value: ast.expr, context: PythonFileContext, *, at: ast.AST | None = None) -> bool:
    if isinstance(value, ast.Constant):
        return value.value is Ellipsis
    if not isinstance(value, ast.Name) or value.id != "Ellipsis":
        return False
    anchor = value if at is None else at
    inventory = context.binding_inventory
    if (
        inventory.wildcard
        or not context.static_resource_provenance.builtin_namespace_untouched
        or type_parameter_shadow("Ellipsis", anchor, context)
    ):
        return False
    scope = inventory.scope(anchor)
    while scope is not None:
        if "Ellipsis" in inventory.bindings.get(scope, {}):
            return False
        scope = inventory.scope(scope)
    return True


def model_namespace_hazards(
    context: PythonFileContext, *, include_settings: bool = False, escape_symbols: frozenset[str] | None = None
) -> bool:
    modules = _SENSITIVE_MODULES | {"pydantic_settings"} if include_settings else _SENSITIVE_MODULES
    return (
        context.has_wildcard_import
        or native_namespace_capability_escapes(context)
        or _mutated_imports(context, modules)
        or _ambiguous_imports(context, modules)
        or _escaped_imports(context, modules, escape_symbols)
        or dynamic_namespace_access(context.nodes(ast.AST), context.imports, context.parents)
    )


def direct_models(
    context: PythonFileContext, *, methods: bool = False, include_settings: bool = False
) -> tuple[ast.ClassDef, ...]:
    tree = context.tree
    if tree is None or context.generated or model_namespace_hazards(context, include_settings=include_settings):
        return ()
    provenance = context.static_resource_provenance
    return tuple(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and len(node.bases) == 1
        and (
            context.imports.resolves(node.bases[0], sources=MODEL_SOURCES, symbol="BaseModel")
            or (
                include_settings
                and context.module_imports.resolves(node.bases[0], sources=SETTINGS_SOURCES, symbol="BaseSettings")
            )
        )
        and not node.decorator_list
        and not node.keywords
        and not node.type_params
        and all(_plain_member(member, context, provenance, methods=methods) for member in node.body)
    )


def _plain_member(node: ast.stmt, context: PythonFileContext, provenance: ResourceProvenance, *, methods: bool) -> bool:
    match node:
        case ast.AnnAssign(target=ast.Name(id=name), annotation=annotation, value=value):
            return (
                not name.startswith("__")
                and inert_annotation(annotation, context)
                and (value is None or inert_class_value(context, value, provenance, pydantic_fields=True))
            )
        case ast.Assign(targets=targets, value=value):
            return all(
                isinstance(target, ast.Name) and not target.id.startswith("__") for target in targets
            ) and inert_class_value(context, value, provenance, pydantic_fields=True)
        case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
            return (
                methods and not name.startswith("__") and name != "model_post_init" and inert_signature(node, context)
            )
        case ast.Pass() | ast.Expr(value=ast.Constant(value=str())):
            return True
        case _:
            return False


def inert_annotation(node: ast.expr, context: PythonFileContext) -> bool:
    if isinstance(node, (ast.Tuple, ast.List)):
        return all(inert_annotation(element, context) for element in node.elts)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError, UnicodeError:
            return False
    return _inert_expr(node, context)


def inert_signature(node: ast.FunctionDef | ast.AsyncFunctionDef, context: PythonFileContext) -> bool:
    if node.type_params:
        return False
    arguments = (
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
        *((node.args.vararg,) if node.args.vararg else ()),
        *((node.args.kwarg,) if node.args.kwarg else ()),
    )
    annotations = [argument.annotation for argument in arguments if argument.annotation is not None]
    if node.returns is not None:
        annotations.append(node.returns)
    defaults = (*node.args.defaults, *(value for value in node.args.kw_defaults if value is not None))
    return all(inert_annotation(annotation, context) for annotation in annotations) and all(
        _inert_expr(value, context) for value in defaults
    )


def _inert_expr(node: ast.AST, context: PythonFileContext) -> bool:
    pending = [node]
    while pending:
        current = pending.pop()
        if isinstance(current, ast.Subscript) and not _inert_subscription(current, context):
            return False
        if isinstance(current, ast.Lambda):
            if current.args.defaults or current.args.kw_defaults:
                return False
            continue
        if isinstance(current, ast.Call) and not _inert_pydantic_call(current, context):
            return False
        if isinstance(
            current,
            (
                ast.NamedExpr,
                ast.Starred,
                ast.Await,
                ast.Yield,
                ast.YieldFrom,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
            ),
        ):
            return False
        pending.extend(reversed(tuple(ast.iter_child_nodes(current))))
    return True


def _inert_pydantic_call(node: ast.Call, context: PythonFileContext) -> bool:
    target = context.imports.resolved_qualified_name(node.func)
    if target not in {
        "pydantic.Field",
        "pydantic.fields.Field",
        "pydantic.ConfigDict",
        "pydantic.config.ConfigDict",
    }:
        return False
    return not any(keyword.arg is None for keyword in node.keywords) and not any(
        isinstance(argument, ast.Starred) for argument in node.args
    )


def _inert_subscription(node: ast.Subscript, context: PythonFileContext) -> bool:
    symbol = context.imports.resolved_symbol(node.value, sources=TYPING_SOURCES)
    if symbol is None and not (
        (
            isinstance(node.value, ast.Name)
            and node.value.id in _GENERIC_BUILTINS
            and context.imports.builtin_is_unshadowed(node.value.id)
        )
        or context.imports.resolved_symbol(node.value, sources=_BUILTIN_SOURCES) in _GENERIC_BUILTINS
    ):
        return False
    arguments = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    if symbol == "Literal":
        return True
    if symbol == "Annotated":
        return bool(arguments) and inert_annotation(arguments[0], context)
    return all(inert_annotation(argument, context) for argument in arguments)


def literal_value(value: ast.expr) -> bool:
    if any(isinstance(node, ast.Call) for node in ast.walk(value)):
        return False
    try:
        ast.literal_eval(value)
    except ValueError, TypeError, SyntaxError, RecursionError, OverflowError:
        return False
    return True


def inert_class_value(
    context: PythonFileContext, value: ast.expr, provenance: ResourceProvenance, *, pydantic_fields: bool
) -> bool:
    if not isinstance(value, ast.Call):
        return literal_value(value) or required_default_sentinel(value, context)
    qualified = context.module_imports.resolved_qualified_name(value.func)
    if (
        not pydantic_fields
        or qualified
        not in {"pydantic.Field", "pydantic.fields.Field", "pydantic.ConfigDict", "pydantic.config.ConfigDict"}
        or not provenance.imported(value.func, qualified)
    ):
        return False
    field_call = qualified in {"pydantic.Field", "pydantic.fields.Field"}
    return all(
        literal_value(argument) or (field_call and index == 0 and required_default_sentinel(argument, context))
        for index, argument in enumerate(value.args)
    ) and all(
        keyword.arg is not None
        and (
            literal_value(keyword.value)
            or (field_call and keyword.arg == "default" and required_default_sentinel(keyword.value, context))
            or (
                keyword.arg == "default_factory"
                and isinstance(keyword.value, ast.Name)
                and keyword.value.id in {"dict", "list", "set", "tuple", "str", "int", "float", "bool"}
                and context.imports.builtin_is_unshadowed(keyword.value.id)
                and provenance.builtin_namespace_untouched
            )
        )
        for keyword in value.keywords
    )


def _mutated_imports(context: PythonFileContext, modules: frozenset[str]) -> bool:
    for node in context.nodes(ast.Attribute, ast.Subscript, ast.Call):
        if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if _sensitive_import_root(node, context, modules):
                return True
        elif (
            isinstance(node, ast.Call)
            and node.args
            and _is_attribute_mutator(node.func, context)
            and _sensitive_import_root(node.args[0], context, modules)
        ):
            return True
    return False


def _sensitive_import_root(node: ast.expr, context: PythonFileContext, modules: frozenset[str]) -> bool:
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    binding = context.module_imports.bindings.get(node.id) if isinstance(node, ast.Name) else None
    return binding is not None and binding.module.partition(".")[0] in modules


def _is_attribute_mutator(node: ast.expr, context: PythonFileContext) -> bool:
    names = {"setattr", "delattr"}
    return (
        isinstance(node, ast.Name) and node.id in names and context.imports.builtin_is_unshadowed(node.id)
    ) or context.imports.resolved_symbol(node, sources=frozenset({"builtins"})) in names


def _escaped_imports(
    context: PythonFileContext, modules: frozenset[str], symbols: frozenset[str] | None = None
) -> bool:
    for node in context.nodes(ast.Name, ast.Attribute):
        if not isinstance(node.ctx, ast.Load) or not _sensitive_import_root(node, context, modules):
            continue
        parent = context.parents.get(node)
        if isinstance(parent, ast.Attribute) and parent.value is node:
            continue
        if symbols is not None and not _escape_in_scope(node, context, symbols):
            continue
        if (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING") or _type_reference(node, parent):
            continue
        return True
    return False


def _escape_in_scope(node: ast.expr, context: PythonFileContext, symbols: frozenset[str]) -> bool:
    qualified = context.module_imports.resolved_qualified_name(node)
    # A whole module stays a namespace capability even when named symbols are narrowed.
    return qualified is None or any(qualified == symbol or symbol.startswith(f"{qualified}.") for symbol in symbols)


def _type_reference(node: ast.expr, parent: ast.AST | None) -> bool:
    match parent:
        case ast.Call(func=func):
            return func is node
        case ast.ClassDef(bases=bases):
            return node in bases
        case ast.Subscript(value=value):
            return value is node
        case (
            ast.arg(annotation=annotation)
            | ast.AnnAssign(annotation=annotation)
            | ast.FunctionDef(returns=annotation)
            | ast.AsyncFunctionDef(returns=annotation)
        ):
            return annotation is node
        case _:
            return False


def _ambiguous_imports(context: PythonFileContext, modules: frozenset[str]) -> bool:
    return any(
        _nested_namespace_import(node, context, modules) or _ambiguous_import(node, context, modules)
        for node in context.nodes(ast.Import, ast.ImportFrom)
    )


def _nested_namespace_import(
    node: ast.Import | ast.ImportFrom, context: PythonFileContext, modules: frozenset[str]
) -> bool:
    if context.parents.get(node) is context.tree:
        return False
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").partition(".")[0] in modules
    return any(alias.name.partition(".")[0] in modules for alias in node.names)


def _ambiguous_import(node: ast.Import | ast.ImportFrom, context: PythonFileContext, modules: frozenset[str]) -> bool:
    for alias in node.names:
        name = alias.asname or alias.name.partition(".")[0]
        if name in _BUILTIN_BINDINGS:
            return True
        binding = context.module_imports.bindings.get(name)
        if binding is None or binding.module.partition(".")[0] not in modules - {"builtins"}:
            continue
        if context.parents.get(node) is not context.tree:
            return True
        if isinstance(node, ast.ImportFrom) and (
            node.level != 0 or node.module != binding.module or alias.name != binding.symbol
        ):
            return True
    return False


def unique_members(model: ast.ClassDef) -> frozenset[str]:
    names: list[str] = []
    for member in model.body:
        match member:
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name) | ast.AnnAssign(target=ast.Name(id=name)):
                names.append(name)
            case ast.Assign(targets=targets):
                names.extend(target.id for target in targets if isinstance(target, ast.Name))
            case _:
                pass
    return frozenset(name for name, count in Counter(names).items() if count == 1)


def has_alias_validation_options(context: PythonFileContext) -> bool:
    root = distribution_root(context.path, facts=context.session.first_party)
    if root is None:
        return False
    try:
        source = (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return False
    return _declares_alias_validation_options(source)


@lru_cache(maxsize=256)
def _declares_alias_validation_options(source: str) -> bool:
    try:
        document = _parse_toml(source)
    except tomllib.TOMLDecodeError:
        return False
    if not is_object_mapping(document):
        return False
    project = document.get("project")
    if not is_object_mapping(project):
        return False
    dependencies = project.get("dependencies")
    if not _is_object_list(dependencies):
        return False
    return any(_alias_dependency(raw) for raw in dependencies)


def _alias_dependency(raw: object) -> bool:
    if not isinstance(raw, str):
        return False
    try:
        requirement = Requirement(raw)
    except InvalidRequirement:
        return False
    if requirement.name.casefold() != "pydantic" or requirement.marker is not None or requirement.url is not None:
        return False
    for specifier in requirement.specifier:
        if specifier.operator not in {">", ">=", "==", "===", "~="}:
            continue
        try:
            version = Version(specifier.version.removesuffix(".*"))
        except InvalidVersion:
            continue
        if version >= _ALIAS_VERSION and version.major == _ALIAS_VERSION.major:
            return True
    return False


def _parse_toml(source: str) -> object:
    return tomllib.loads(source)


def _is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)
