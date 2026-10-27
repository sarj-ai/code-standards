from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, ClassVar, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
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
from sarj_python_lint.rules._ast_index import walk as walk_ast
from sarj_python_lint.rules._ast_names import expression_root as _expression_root
from sarj_python_lint.rules._namespace_access import dynamic_namespace_access


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex
    from sarj_python_lint.rules._imports import ImportIndex


_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_PYDANTIC_SOURCES = frozenset({"pydantic"})
_MAPPING_SOURCES = frozenset({"collections.abc", "typing"})
_MAPPING_NAMES = frozenset({"dict", "Dict", "Mapping", "MutableMapping"})
_MAPPING_ARGUMENT_COUNT = 2
_BUILTIN_TYPE_CONTAINERS = frozenset({"dict", "list", "set", "frozenset", "tuple", "type"})
_TYPE_MODULES = frozenset({"typing", "typing_extensions", "pydantic", "collections", "builtins"})
_TYPE_COMMENT_MARKER = re.compile(r"#\s*type:")


@dataclass(frozen=True, slots=True)
class _TypeReferenceContext:
    semantics: AnnotationSemantics
    parents: Mapping[ast.AST, ast.AST]
    implicit_aliases: frozenset[int]


@dataclass(frozen=True, slots=True)
class _TypeOrigins:
    names: frozenset[str]
    namespaces: frozenset[str]


@final
class NoAnyMappingTypes(Rule):
    id = "no-any-mapping-types"
    code = "SARJ447"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.ERROR,
        summary="String-keyed mapping types must not erase their values with `Any`.",
        rationale=(
            "An `Any`-valued mapping disables checking transitively and conceals whether the value is a fixed record, "
            "an arbitrary JSON tree, or a genuinely opaque Python object."
        ),
        remediation=(
            "Use `TypedDict` (and `Unpack[TypedDict]` for closed keyword arguments) for fixed records, a Pydantic model "
            "for untrusted runtime input, `pydantic.JsonValue` for arbitrary JSON, or `object` plus explicit narrowing "
            "for a genuinely opaque Python value. Preserve unchanged external API signatures with an exact explained suppression; do not automatically widen published returns."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.SAFE,
        aliases=("no-vague-annotations",),
        limitations=(
            "Automatic fixes replace only direct Any values in covariant Mapping parameters of closed private nested synchronous helpers whose parameter is entirely unused. Defaults, consumers, reflection/frame access, comments, shadowed object, mutable/aliased/string annotations and newly unused Any imports remain manual.",
            "Containing callables must also be ordinary synchronous nongenerators with proven inert execution; unknown callouts, properties, overloads, reachable frame-exporting exceptions, and helper references crossing additional function, class, lambda, or comprehension scopes prevent fixes.",
            (
                "Only proven built-in or standard-library string-keyed mappings whose value recursively contains "
                "`typing.Any` are reported; `object` is intentionally not treated as `Any`."
            ),
            (
                "Unique unconditional module-level PEP 695 and explicit TypeAlias chains are resolved with cycle "
                "guards. Plain module assignments are checked only when they directly define an Any-valued mapping "
                "used in a module-level annotation; imported, conditional, rebound, and ambiguous aliases are excluded."
            ),
            "Generated and vendored sources are excluded; exact local suppressions remain auditable.",
            "Annotated metadata, Literal values and unresolved generic parameter positions are excluded; only type arguments are inspected.",
            "Proven override method signatures and direct BaseModel.model_dump return contracts are excluded; local annotations, casts and TypeAdapter targets remain checked.",
            "Ambiguous type-import origins, attribute mutations, escaped canonical type namespaces and dynamic namespace access cause conservative file abstention.",
        ),
        examples=(
            RuleExample(
                example_id="safe-autofix",
                title="Retain an unused private mapping parameter as opaque objects",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from collections.abc import Mapping\nfrom typing import Any\ndef identity(value: Any) -> Any:\n    return value\ndef outer() -> int:\n    def _accept(payload: Mapping[str, Any]) -> int:\n        return 1\n    return _accept({'key': 1})\n",
                    ),
                ),
                fixed_files=(
                    ExampleFile.python(
                        "app/service.py",
                        "from collections.abc import Mapping\nfrom typing import Any\ndef identity(value: Any) -> Any:\n    return value\ndef outer() -> int:\n    def _accept(payload: Mapping[str, object]) -> int:\n        return 1\n    return _accept({'key': 1})\n",
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
            ),
            RuleExample(
                example_id="any-valued-mapping-annotation",
                title="An Any-valued mapping erases the record schema",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/offers.py", "from typing import Any\ndef details() -> dict[str, Any]: ...\n"
                    ),
                ),
                focus_path=PurePosixPath("app/offers.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="typed-dictionary-annotation",
                title="A TypedDict preserves the record schema",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/offers.py",
                        "from typing import TypedDict\nclass OfferDetails(TypedDict):\n    id: str\ndef details() -> OfferDetails: ...\n",
                    ),
                ),
                focus_path=PurePosixPath("app/offers.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="generic-any-binding",
                scenario="provider-identity",
                title="A generic parameter named Any keeps its own identity",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py", "from typing import Any\nclass Rows[Any]:\n    rows: dict[str, Any]\n"
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="generic-typing-any",
                scenario="provider-identity",
                title="An unrelated generic parameter preserves actual Any erasure",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/service.py", "from typing import Any\nclass Rows[T]:\n    rows: dict[str, Any]\n"
                    ),
                ),
                focus_path=PurePosixPath("app/service.py"),
                expected_count=1,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if context.generated or _is_vendor_path(path):
            return []
        tree = _annotation_tree(context)
        if tree is None:
            return []
        semantics = context.annotation_semantics if tree is context.tree else AnnotationSemantics.from_tree(tree)
        imports = semantics.imports
        parents = (
            context.parents
            if tree is context.tree
            else {child: parent for parent in walk_ast(tree) for child in ast.iter_child_nodes(parent)}
        )
        implicit_aliases = _implicit_mapping_aliases(tree, semantics)
        if not _stable_type_imports(tree, semantics, parents, implicit_aliases) or dynamic_namespace_access(
            context.nodes(ast.AST), imports, context.parents
        ):
            return []
        scope_cache: dict[int, frozenset[str]] = {}
        lines = context.source_lines
        findings: list[Diagnostic] = []
        seen: set[tuple[int, int]] = set()
        expressions = [
            *_type_expressions(tree, imports, parents, scope_cache, node_index=context.node_index),
            *implicit_aliases,
        ]
        for expression, owner in expressions:
            for mapping, location in _unshadowed_any_mappings(expression, owner, semantics, parents, scope_cache):
                key = (location.lineno, location.col_offset)
                if key in seen or is_suppressed(lines, location.lineno, self.code):
                    continue
                seen.add(key)
                findings.append(
                    Diagnostic(
                        path=path,
                        line=location.lineno,
                        col=location.col_offset + 1,
                        code=self.code,
                        message=(
                            f"mapping type `{ast.unparse(mapping)}` contains `Any`; use `TypedDict` for a fixed "
                            "record, `pydantic.JsonValue` for arbitrary JSON, or `object` with narrowing for opaque values"
                        ),
                    )
                )
        return sorted(findings, key=lambda finding: (finding.line, finding.col))


def _annotation_tree(context: PythonFileContext) -> ast.Module | None:
    if _TYPE_COMMENT_MARKER.search(context.source) is None:
        return context.tree
    try:
        return ast.parse(context.source, filename=str(context.path), type_comments=True)
    except SyntaxError, UnicodeError:
        return None


def _implicit_mapping_aliases(tree: ast.Module, semantics: AnnotationSemantics) -> list[tuple[ast.expr, ast.Assign]]:
    bindings = [scope_bound_names([statement]) for statement in tree.body]
    aliases: list[tuple[ast.expr, ast.Assign]] = []
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name) or not isinstance(statement.value, ast.Subscript):
            continue
        if sum(target.id in names for names in bindings) != 1:
            continue
        if _used_in_module_annotation(tree, target.id, semantics):
            aliases.append((statement.value, statement))
    return aliases


def _used_in_module_annotation(tree: ast.Module, name: str, semantics: AnnotationSemantics) -> bool:
    return any(
        _annotation_contains_name(annotation, name, semantics)
        for statement in tree.body
        for annotation in _module_statement_annotations(statement, name)
    )


def _module_statement_annotations(statement: ast.stmt, alias_name: str) -> list[ast.expr]:
    if isinstance(statement, ast.AnnAssign):
        return [statement.annotation]
    if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    arguments = statement.args
    parameters = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    if any(argument.arg == alias_name for argument in parameters):
        return []
    annotations = [argument.annotation for argument in parameters if argument.annotation is not None]
    if statement.returns is not None:
        annotations.append(statement.returns)
    return annotations


def _annotation_contains_name(annotation: ast.expr, name: str, semantics: AnnotationSemantics) -> bool:
    parsed = semantics.parse(annotation)
    if parsed is None:
        return False
    pending = [parsed]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Name) and node.id == name:
            return True
        pending.extend(_type_children(node, semantics))
    return False


def _unshadowed_any_mappings(
    expression: ast.expr,
    owner: ast.AST,
    semantics: AnnotationSemantics,
    parents: Mapping[ast.AST, ast.AST],
    scope_cache: dict[int, frozenset[str]],
) -> list[tuple[ast.Subscript, ast.expr]]:
    parsed = semantics.parse(expression)
    if parsed is None:
        return []
    names = {node.id for node in walk_ast(parsed) if isinstance(node, ast.Name)}
    type_parameters = frozenset(_generic_scope_names(owner, parents))
    if not names.isdisjoint(_shadowed_names(owner, parents, scope_cache) - type_parameters):
        return []
    return [
        (mapping, expression if isinstance(expression, ast.Constant) else mapping)
        for mapping in _any_mappings(expression, semantics, shadowed=type_parameters)
    ]


def _type_expressions(
    tree: ast.Module,
    imports: ImportIndex,
    parents: Mapping[ast.AST, ast.AST],
    scope_cache: dict[int, frozenset[str]],
    *,
    node_index: NodeIndex | None = None,
) -> list[tuple[ast.expr, ast.AST]]:
    expressions = [
        (annotation, node)
        for node in walk_ast(tree, index=node_index)
        if (annotation := _node_annotation(node, imports)) is not None
        and not _inherited_signature(node, imports, parents, scope_cache)
    ]
    for node in walk_ast(tree, index=node_index):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not _unshadowed_type_expression(node.func, parents, scope_cache):
            continue
        if imports.resolves(node.func, sources=_TYPING_SOURCES, symbol="cast") or imports.resolves(
            node.func, sources=_PYDANTIC_SOURCES, symbol="TypeAdapter"
        ):
            expressions.append((node.args[0], node))
    return expressions


def _inherited_signature(
    node: ast.AST,
    imports: ImportIndex,
    parents: Mapping[ast.AST, ast.AST],
    scope_cache: dict[int, frozenset[str]],
) -> bool:
    function: ast.AST | None = node
    if isinstance(node, ast.arg):
        arguments = parents.get(node)
        function = parents.get(arguments) if arguments is not None else None
    if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    owner = parents.get(function)
    if not isinstance(owner, ast.ClassDef):
        return False
    for decorator in function.decorator_list:
        if _class_local_override(decorator, owner):
            return True
        if _unshadowed_type_expression(decorator, parents, scope_cache) and imports.resolves(
            decorator, sources=_TYPING_SOURCES, symbol="override"
        ):
            return True
    return (
        node is function
        and function.name == "model_dump"
        and any(
            _unshadowed_type_expression(base, parents, scope_cache)
            and imports.resolves(base, sources=_PYDANTIC_SOURCES, symbol="BaseModel")
            for base in owner.bases
        )
    )


def _class_local_override(decorator: ast.expr, owner: ast.ClassDef) -> bool:
    name = _expression_root(decorator)
    if name is None:
        return False
    bindings = [statement for statement in owner.body if name in scope_bound_names([statement])]
    if len(bindings) != 1:
        return False
    statement = bindings[0]
    if isinstance(decorator, ast.Name) and isinstance(statement, ast.ImportFrom):
        return (
            statement.level == 0
            and statement.module in _TYPING_SOURCES
            and any(alias.name == "override" and (alias.asname or alias.name) == name for alias in statement.names)
        )
    if isinstance(decorator, ast.Attribute) and decorator.attr == "override" and isinstance(statement, ast.Import):
        return isinstance(decorator.value, ast.Name) and any(
            alias.name in _TYPING_SOURCES and (alias.asname or alias.name) == name for alias in statement.names
        )
    return False


def _stable_type_imports(
    tree: ast.Module,
    semantics: AnnotationSemantics,
    parents: Mapping[ast.AST, ast.AST],
    implicit_aliases: list[tuple[ast.expr, ast.Assign]],
) -> bool:
    imports = semantics.imports
    nodes = tuple(walk_ast(tree))
    references = _TypeReferenceContext(
        semantics, parents, frozenset(id(expression) for expression, _ in implicit_aliases)
    )
    bindings = _type_import_bindings(imports)
    origins = _canonical_type_origins(nodes)
    sensitive = set(bindings.names)
    mutation_roots = set(origins.names | bindings.names)
    namespaces = set(bindings.namespaces | origins.namespaces)
    providers = _mapping_provider_aliases(nodes, _mapping_provider_names(nodes), namespaces)
    mutation_roots.update(providers)
    for node in nodes:
        if isinstance(node, ast.Name) and node.id == "__builtins__":
            return False
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not _canonical_type_import(node, imports, sensitive):
            return False
        if (
            isinstance(node, (ast.Attribute, ast.Subscript))
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and _expression_root(node) in mutation_roots
        ):
            return False
        if isinstance(node, ast.Call) and _type_attribute_mutation(node, imports, mutation_roots):
            return False
        if _type_namespace_escape(node, providers, namespaces, references):
            return False
    return True


def _type_import_bindings(imports: ImportIndex) -> _TypeOrigins:
    sensitive = frozenset(
        name for name, target in imports.bindings.items() if target.module.partition(".")[0] in _TYPE_MODULES
    )
    return _TypeOrigins(sensitive, frozenset(name for name in sensitive if imports.bindings[name].symbol is None))


def _canonical_type_origins(nodes: tuple[ast.AST, ...]) -> _TypeOrigins:
    roots: set[str] = set()
    namespaces: set[str] = set()
    for node in nodes:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        names = _canonical_type_names(node)
        roots.update(names)
        if isinstance(node, ast.Import):
            namespaces.update(names)
    return _TypeOrigins(frozenset(roots), frozenset(namespaces))


def _canonical_type_names(node: ast.Import | ast.ImportFrom) -> set[str]:
    if isinstance(node, ast.ImportFrom):
        if (node.module or "").partition(".")[0] not in _TYPE_MODULES:
            return set()
        return {alias.asname or alias.name for alias in node.names}
    return {
        alias.asname or module_root
        for alias in node.names
        if (module_root := alias.name.partition(".")[0]) in _TYPE_MODULES
    }


def _mapping_provider_names(nodes: tuple[ast.AST, ...]) -> set[str]:
    return {
        alias.asname or alias.name
        for node in nodes
        if isinstance(node, ast.ImportFrom) and node.module in _MAPPING_SOURCES
        for alias in node.names
        if alias.name in _MAPPING_NAMES
    }


def _mapping_provider_aliases(nodes: tuple[ast.AST, ...], providers: set[str], namespaces: set[str]) -> set[str]:
    dependencies: dict[str, set[str]] = {}
    known = set(providers)
    for statement in nodes:
        alias = _mapping_alias_assignment(statement)
        if alias is None:
            continue
        name, value = alias
        for node in walk_ast(value):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                dependencies.setdefault(node.id, set()).add(name)
            elif _mapping_provider_reference(node, providers, namespaces):
                known.add(name)
    pending = list(known)
    while pending:
        for alias in dependencies.get(pending.pop(), ()):
            if alias not in known:
                known.add(alias)
                pending.append(alias)
    return known


def _mapping_alias_assignment(node: ast.AST) -> tuple[str, ast.expr] | None:
    if isinstance(node, ast.TypeAlias):
        target, value = node.name, node.value
    elif isinstance(node, ast.AnnAssign):
        target, value = node.target, node.value
    elif isinstance(node, ast.Assign) and len(node.targets) == 1:
        target, value = node.targets[0], node.value
    else:
        return None
    if not isinstance(target, ast.Name) or not isinstance(
        value, (ast.Name, ast.Attribute, ast.Subscript, ast.BinOp, ast.Tuple, ast.List)
    ):
        return None
    return target.id, value


def _type_namespace_escape(
    node: ast.AST, providers: set[str], namespaces: set[str], references: _TypeReferenceContext
) -> bool:
    if _mapping_provider_reference(node, providers, namespaces):
        return isinstance(node, ast.expr) and not _provider_type_reference(node, references)
    if isinstance(node, ast.Attribute) and _expression_root(node) in namespaces:
        return node.attr != "Any" and _bare_runtime_value(node, references.parents)
    if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load) or node.id not in namespaces:
        return False
    parent = references.parents.get(node)
    return (
        not isinstance(parent, ast.Attribute)
        or parent.value is not node
        or parent.attr in {"__dict__", "__setattr__", "__delattr__", "__getattribute__"}
    )


def _bare_runtime_value(node: ast.expr, parents: Mapping[ast.AST, ast.AST]) -> bool:
    parent = parents.get(node)
    return isinstance(parent, (ast.Assign, ast.AnnAssign, ast.NamedExpr, ast.Return)) and parent.value is node


def _mapping_provider_reference(node: ast.AST, providers: set[str], namespaces: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return isinstance(node.ctx, ast.Load) and node.id in providers
    return isinstance(node, ast.Attribute) and node.attr in _MAPPING_NAMES and _expression_root(node) in namespaces


def _provider_type_reference(node: ast.expr, references: _TypeReferenceContext) -> bool:
    parent = references.parents.get(node)
    if isinstance(parent, ast.Call) and parent.func is node:
        return True
    if isinstance(parent, ast.ClassDef) and node in parent.bases:
        return True
    root = node
    while isinstance(parent, (ast.Subscript, ast.Tuple, ast.List, ast.BinOp)):
        root, parent = parent, references.parents.get(parent)
    annotation = _node_annotation(parent, references.semantics.imports) if parent is not None else None
    if (
        annotation is root
        or id(root) in references.implicit_aliases
        or _runtime_type_argument(root, parent, references.semantics.imports)
    ):
        return _contains_type_reference(root, node, references.semantics)
    return False


def _runtime_type_argument(node: ast.expr, parent: ast.AST | None, imports: ImportIndex) -> bool:
    if not isinstance(parent, ast.Call) or not parent.args or parent.args[0] is not node:
        return False
    return imports.resolves(parent.func, sources=_TYPING_SOURCES, symbol="cast") or imports.resolves(
        parent.func, sources=_PYDANTIC_SOURCES, symbol="TypeAdapter"
    )


def _contains_type_reference(root: ast.expr, target: ast.expr, semantics: AnnotationSemantics) -> bool:
    pending: list[ast.expr] = [root]
    while pending:
        node = pending.pop()
        if node is target or (isinstance(node, ast.Subscript) and node.value is target):
            return True
        pending.extend(_type_children(node, semantics))
    return False


def _canonical_type_import(node: ast.Import | ast.ImportFrom, imports: ImportIndex, sensitive: set[str]) -> bool:
    for alias in node.names:
        if alias.name == "*":
            return False
        name = alias.asname or alias.name.partition(".")[0]
        if name in _BUILTIN_TYPE_CONTAINERS | {"str"}:
            return False
        if name not in sensitive:
            continue
        binding = imports.bindings[name]
        if isinstance(node, ast.ImportFrom):
            if node.level or node.module != binding.module or alias.name != binding.symbol:
                return False
        elif binding.symbol is not None or (alias.name if alias.asname else name) != binding.module:
            return False
    return True


def _type_attribute_mutation(call: ast.Call, imports: ImportIndex, sensitive: set[str]) -> bool:
    if not call.args:
        return False
    mutators = {"setattr", "delattr"}
    known = (
        isinstance(call.func, ast.Name) and call.func.id in mutators and imports.builtin_is_unshadowed(call.func.id)
    ) or imports.resolved_symbol(call.func, sources=frozenset({"builtins"})) in mutators
    return known and _expression_root(call.args[0]) in sensitive


def _unshadowed_type_expression(
    node: ast.expr, parents: Mapping[ast.AST, ast.AST], scope_cache: dict[int, frozenset[str]]
) -> bool:
    names = {child.id for child in walk_ast(node) if isinstance(child, ast.Name)}
    return names.isdisjoint(_shadowed_names(node, parents, scope_cache))


def _generic_scope_names(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> set[str]:
    names = _type_parameter_names(node)
    below = node
    parent = parents.get(below)
    function_default = False
    while parent is not None:
        match parent:
            case ast.arguments():
                function_default = below in parent.defaults or below in parent.kw_defaults
            case ast.FunctionDef() | ast.AsyncFunctionDef():
                if not function_default and below not in parent.decorator_list:
                    names.update(_type_parameter_names(parent))
                function_default = False
            case ast.Lambda():
                function_default = False
            case ast.ClassDef():
                if below not in parent.decorator_list:
                    names.update(_type_parameter_names(parent))
            case ast.TypeAlias():
                names.update(_type_parameter_names(parent))
            case _:
                pass
        below = parent
        parent = parents.get(below)
    return names


def _shadowed_names(
    node: ast.AST,
    parents: Mapping[ast.AST, ast.AST],
    scope_cache: dict[int, frozenset[str]],
) -> set[str]:
    shadowed = _generic_scope_names(node, parents)
    crossed_function_body = False
    below = node
    parent = parents.get(below)
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if below in parent.body:
                crossed_function_body = True
                shadowed.update(_scope_names(parent, scope_cache))
        elif isinstance(parent, ast.ClassDef) and below in parent.body and not crossed_function_body:
            shadowed.update(_scope_names(parent, scope_cache))
        below = parent
        parent = parents.get(below)
    return shadowed


def _type_parameter_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.TypeAlias)):
        return {
            parameter.name
            for parameter in node.type_params
            if isinstance(parameter, (ast.TypeVar, ast.ParamSpec, ast.TypeVarTuple))
        }
    return set()


def _scope_names(
    owner: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    cache: dict[int, frozenset[str]],
) -> frozenset[str]:
    key = id(owner)
    if (cached := cache.get(key)) is not None:
        return cached
    names = scope_bound_names(owner.body)
    if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
        names.update(
            argument.arg
            for argument in (
                *owner.args.posonlyargs,
                *owner.args.args,
                *owner.args.kwonlyargs,
                *((owner.args.vararg,) if owner.args.vararg is not None else ()),
                *((owner.args.kwarg,) if owner.args.kwarg is not None else ()),
            )
        )
    result = frozenset(names)
    cache[key] = result
    return result


def _node_annotation(node: ast.AST, imports: ImportIndex) -> ast.expr | None:
    match node:
        case (
            ast.arg(annotation=annotation)
            | ast.FunctionDef(returns=annotation)
            | ast.AsyncFunctionDef(returns=annotation)
        ):
            return annotation
        case ast.AnnAssign(annotation=annotation, value=value) if value is not None:
            if imports.resolves(annotation, sources=_TYPING_SOURCES, symbol="TypeAlias"):
                return value
            return annotation
        case ast.AnnAssign(annotation=annotation):
            return annotation
        case ast.TypeAlias(value=value):
            return value
        case (
            ast.Assign(type_comment=str(comment))
            | ast.For(type_comment=str(comment))
            | ast.AsyncFor(type_comment=str(comment))
            | ast.With(type_comment=str(comment))
            | ast.AsyncWith(type_comment=str(comment))
        ):
            return _type_comment(comment, node)
        case _:
            return None


def _type_comment(comment: str, owner: ast.AST) -> ast.expr | None:
    try:
        expression = ast.parse(comment, mode="eval").body
    except SyntaxError:
        return None
    ast.copy_location(expression, owner)
    return expression


def _any_mappings(
    annotation: ast.expr, semantics: AnnotationSemantics, *, shadowed: frozenset[str] = frozenset()
) -> list[ast.Subscript]:
    resolved = semantics.parse(annotation)
    if resolved is None:
        return []
    pending = [resolved]
    mappings: list[ast.Subscript] = []
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Subscript) and _is_any_mapping(node, semantics, shadowed=shadowed):
            mappings.append(node)
        pending.extend(_type_children(node, semantics, shadowed=shadowed))
    return mappings


def _is_any_mapping(node: ast.Subscript, semantics: AnnotationSemantics, *, shadowed: frozenset[str]) -> bool:
    if not isinstance(node.slice, ast.Tuple) or len(node.slice.elts) != _MAPPING_ARGUMENT_COUNT:
        return False
    imports = semantics.imports
    target = node.value
    if _expression_root(target) in shadowed:
        return False
    mapping = (isinstance(target, ast.Name) and target.id == "dict" and imports.builtin_is_unshadowed("dict")) or any(
        imports.resolves(target, sources=_MAPPING_SOURCES, symbol=name) for name in _MAPPING_NAMES
    )
    if not mapping:
        return False
    key, value = node.slice.elts
    return (
        _expression_root(key) not in shadowed
        and _is_builtin_str(key, imports)
        and _contains_any(value, semantics, seen=frozenset(), shadowed=shadowed)
    )


def _is_builtin_str(node: ast.expr, imports: ImportIndex) -> bool:
    return isinstance(node, ast.Name) and node.id == "str" and imports.builtin_is_unshadowed("str")


def _contains_any(
    node: ast.expr,
    semantics: AnnotationSemantics,
    *,
    seen: frozenset[str],
    shadowed: frozenset[str] = frozenset(),
) -> bool:
    parsed = semantics.parse(node)
    if parsed is None or _expression_root(parsed) in shadowed:
        return False
    imports = semantics.imports
    if imports.resolves(parsed, sources=_TYPING_SOURCES, symbol="Any"):
        return True
    if isinstance(parsed, ast.Name) and parsed.id in semantics.aliases and parsed.id not in seen:
        # Module aliases resolve in declaration scope, independent of generic names at the use site.
        return _contains_any(semantics.aliases[parsed.id], semantics, seen=seen | {parsed.id})
    return any(
        _contains_any(child, semantics, seen=seen, shadowed=shadowed)
        for child in _type_children(parsed, semantics, shadowed=shadowed)
    )


def _type_children(
    node: ast.expr, semantics: AnnotationSemantics, *, shadowed: frozenset[str] = frozenset()
) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Subscript):
        if _expression_root(node.value) in shadowed:
            return ()
        imports = semantics.imports
        symbol = imports.resolved_symbol(node.value, sources=_TYPING_SOURCES | _MAPPING_SOURCES)
        if symbol == "Literal":
            return ()
        members = tuple(node.slice.elts) if isinstance(node.slice, ast.Tuple) else (node.slice,)
        if symbol == "Annotated":
            return members[:1]
        builtin = (
            isinstance(node.value, ast.Name)
            and node.value.id in _BUILTIN_TYPE_CONTAINERS
            and imports.builtin_is_unshadowed(node.value.id)
        )
        return members if builtin or symbol is not None else ()
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return node.left, node.right
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(node.elts)
    return ()


def _is_vendor_path(path: Path) -> bool:
    return any(part.casefold() in {"vendor", "vendored", "third_party"} for part in path.parts)
