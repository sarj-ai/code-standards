from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from sarj_python_lint.rules._fastapi import HTTP_METHODS
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._resource_provenance import import_name_for_binding


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._fastapi import Route
    from sarj_python_lint.rules._project_index import ProjectIndexSet

_MAX_ALIAS_DEPTH = 8
_MAX_MOUNT_NODES = 4096
_ROUTER_METHODS = HTTP_METHODS | {"include_router"}


class FastapiAccessFacts:
    def __init__(self) -> None:
        self.project: ProjectIndexSet | None = None
        self.graph: FastapiAccessGraph | None = None

    def for_context(self, context: PythonFileContext) -> FastapiAccessGraph:
        project = context.session.project
        if project is None:
            return FastapiAccessGraph((context,), None)
        if self.project is not project or self.graph is None:
            # Reuse the prepared graph; never rediscover files for individual routes.
            from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- file contexts own this session's lazy facts.

            contexts = tuple(
                PythonFileContext(unit.path, unit.source, context.session)
                for unit in project.source_units
                if unit.tree is not None
                and not is_test_path(unit.path)
                and ("fastapi" in unit.source or "include_router" in unit.source)
            )
            self.graph = FastapiAccessGraph(contexts, project)
            self.project = project
        return self.graph


@dataclass(frozen=True)
class _Mount:
    parent: tuple[Path, str]
    declared: bool
    unpacked: bool


@dataclass
class _MountEvaluation:
    remaining: int = _MAX_MOUNT_NODES
    known: dict[tuple[Path, str], bool] = field(default_factory=dict)


class FastapiAccessGraph:
    def __init__(self, contexts: tuple[PythonFileContext, ...], project: ProjectIndexSet | None) -> None:
        contexts = tuple(sorted(contexts, key=lambda context: context.path))
        self.contexts = {context.path.resolve(): context for context in contexts}
        self.project = project
        self.defaults: dict[tuple[Path, str], bool] = {}
        self.mounts: dict[tuple[Path, str], list[_Mount]] = {}
        self.uncertain: set[tuple[Path, str]] = set()
        self._mutations: dict[Path, frozenset[ast.AST]] = {}
        for context in contexts:
            self.uncertain.update(
                (context.path.resolve(), f"{key.scope}:{key.name}") for key in context.fastapi.unpacked_receivers
            )
            for receiver, dependency in context.fastapi.access_dependencies.items():
                self.defaults[context.path.resolve(), receiver] = dependency is not None and SecurityResolver(
                    context,
                    mutated=self.mutations(context),
                ).declares(dependency)
        for context in contexts:
            self._read_mounts(context)

    def _receiver(
        self,
        context: PythonFileContext,
        expression: ast.expr,
        seen: frozenset[tuple[Path, str]] = frozenset(),
        *,
        at: ast.AST | None = None,
    ) -> tuple[Path, str] | None:
        if (identity := context.fastapi.receiver_identity(expression)) is not None:
            return context.path.resolve(), identity
        if self.project is None or len(seen) >= _MAX_ALIAS_DEPTH:
            return None
        root = expression
        while isinstance(root, ast.Attribute):
            root = root.value
        provenance = context.static_resource_provenance
        if (
            not isinstance(root, ast.Name)
            or provenance.dynamic_namespace
            or provenance.wildcard
            or root.id in provenance.mutated
            or not isinstance(provenance.runtime_binding(root.id, expression if at is None else at), ast.alias)
        ):
            return None
        unit = self.project.unit(context.path)
        symbol = None if unit is None else self.project.resolve(unit, expression)
        target = None if symbol is None else self.project.source_unit(symbol.module)
        if symbol is None or target is None or (key := (target.path, symbol.name)) in seen:
            return None
        target_context = self.contexts.get(target.path)
        if target_context is None:
            from sarj_python_lint._file_context import PythonFileContext  # ruff: ignore[import-outside-top-level] -- borrow an imported re-export from the existing prepared graph.

            target_context = PythonFileContext(target.path, target.source, context.session)
            self.contexts[target.path] = target_context
        if target.tree is None or not target.tree.body:
            return None
        return self._receiver(
            target_context, ast.Name(id=symbol.name, ctx=ast.Load()), seen | {key}, at=target.tree.body[0]
        )

    def _read_mounts(self, context: PythonFileContext) -> None:
        for call in context.nodes(ast.Call):
            if not isinstance(call.func, ast.Attribute) or call.func.attr != "include_router":
                continue
            parent = self._receiver(context, call.func.value)
            argument = call.args[0] if call.args else _keyword(call, "router")
            child = None if argument is None else self._receiver(context, argument)
            if parent is None or child is None:
                continue
            dependency = _keyword(call, "dependencies")
            declared = dependency is not None and SecurityResolver(context, mutated=self.mutations(context)).declares(
                dependency
            )
            self.mounts.setdefault(child, []).append(
                _Mount(parent, declared, any(keyword.arg is None for keyword in call.keywords))
            )

    def mutations(self, context: PythonFileContext) -> frozenset[ast.AST]:
        key = context.path.resolve()
        if key not in self._mutations:
            self._mutations[key] = self._mutation_bindings(context)
        return self._mutations[key]

    def _mutation_bindings(self, context: PythonFileContext) -> frozenset[ast.AST]:
        provenance = context.static_resource_provenance
        aliases = _alias_graph(context)
        mutated = {
            binding
            for node in context.nodes(ast.Name)
            if isinstance(node.ctx, ast.Load)
            and (binding := provenance.runtime_binding(node.id, node)) is not None
            and self._reference_mutates(context, node)
        }
        pending = list(mutated)
        while pending:
            for alias in aliases.get(pending.pop(), ()):
                if alias not in mutated:
                    mutated.add(alias)
                    pending.append(alias)
        return frozenset(mutated)

    def _reference_mutates(self, context: PythonFileContext, node: ast.Name) -> bool:
        parent = context.parents.get(node)
        while isinstance(parent, ast.List | ast.Tuple | ast.Set | ast.Dict | ast.Starred | ast.BinOp):
            parent = context.parents.get(parent)
        if self._dependency_keyword(context, parent):
            return False
        if isinstance(parent, ast.Assign | ast.AnnAssign) and parent.value is node:
            targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
            return any(not isinstance(target, ast.Name) for target in targets)
        return isinstance(parent, ast.Attribute | ast.Subscript | ast.Call | ast.keyword)

    def _dependency_keyword(self, context: PythonFileContext, node: ast.AST | None) -> bool:
        if not isinstance(node, ast.keyword) or node.arg != "dependencies":
            return False
        call = context.parents.get(node)
        if not isinstance(call, ast.Call):
            return False
        if context.fastapi.constructor_kind(call) is not None:
            return True
        return (
            isinstance(call.func, ast.Attribute)
            and call.func.attr in _ROUTER_METHODS
            and self._receiver(context, call.func.value) is not None
        )

    def protected(self, path: Path, receiver: str) -> bool | None:
        return self._protected((path.resolve(), receiver), frozenset(), _MountEvaluation())

    def _protected(
        self, key: tuple[Path, str], seen: frozenset[tuple[Path, str]], proof: _MountEvaluation
    ) -> bool | None:
        if (known := proof.known.get(key)) is not None:
            return known
        if self.defaults.get(key, False):
            return True
        if key in self.uncertain:
            return None
        if key in seen or len(seen) >= _MAX_ALIAS_DEPTH or proof.remaining <= 0:
            return None
        proof.remaining -= 1
        parents = self.mounts.get(key, ())
        if not parents:
            proof.known[key] = False
            return False
        unknown = False
        for mount in parents:
            if proof.remaining <= 0:
                return None
            result = self._mount_protected(mount, seen | {key}, proof)
            if result is False:
                proof.known[key] = False
                return False
            if result is None:
                unknown = True
        if unknown:
            return None
        proof.known[key] = True
        return True

    def _mount_protected(
        self, mount: _Mount, seen: frozenset[tuple[Path, str]], proof: _MountEvaluation
    ) -> bool | None:
        if mount.declared:
            return True
        if mount.unpacked:
            return None
        return self._protected(mount.parent, seen, proof)


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _alias_graph(context: PythonFileContext) -> dict[ast.AST, set[ast.AST]]:
    provenance = context.static_resource_provenance
    aliases: dict[ast.AST, set[ast.AST]] = {}
    for statement in context.nodes(ast.Assign, ast.AnnAssign):
        if not isinstance(statement.value, ast.Name):
            continue
        binding = provenance.runtime_binding(statement.value.id, statement.value)
        if binding is None:
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            other = provenance.runtime_binding(target.id, target)
            if other is not None:
                aliases.setdefault(binding, set()).add(other)
                aliases.setdefault(other, set()).add(binding)
    return aliases


class SecurityResolver:
    def __init__(self, context: PythonFileContext, *, mutated: frozenset[ast.AST]) -> None:
        self._context = context
        self._index = context.fastapi
        self._mutated = mutated

    def route_declares_security(self, route: Route) -> bool:
        return any(
            node is not None and self._declares(node, 0)
            for node in (route.keywords.get("dependencies"), route.inherited_dependencies)
        )

    def declares(self, node: ast.expr) -> bool:
        return self._declares(node, 0)

    def parameters_declare_security(self, function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        arguments = function.args
        parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        defaults = [default for default in (*arguments.defaults, *arguments.kw_defaults) if default is not None]
        return any(
            self._annotation_declares(parameter.annotation, parameter.annotation, 0) for parameter in parameters
        ) or any(self._is_security(default, default, annotation=False) for default in defaults)

    def _annotation_declares(self, annotation: ast.expr | None, at: ast.AST | None, depth: int) -> bool:
        if annotation is None or depth > _MAX_ALIAS_DEPTH:
            return False
        if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
            try:
                parsed = ast.parse(annotation.value, mode="eval").body
            except SyntaxError:
                return False
            return self._annotation_declares(parsed, at, depth + 1)
        if isinstance(annotation, ast.Name) and at is not None:
            binding = self._context.static_resource_provenance.binding(annotation.id, at)
            if binding is None:
                return False
            value = self._bound_value(binding)
            if value is not None:
                return self._annotation_declares(value, value, depth + 1)
            return isinstance(binding, ast.alias) and self._index.is_imported_security_alias(annotation)
        if isinstance(annotation, ast.Subscript) and self._import_name(annotation.value, at, annotation=True) in {
            "typing.Annotated",
            "typing_extensions.Annotated",
        }:
            parts = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
            return any(self._is_security(item, at, annotation=True) for item in parts[1:])
        return False

    def _is_security(self, node: ast.expr, at: ast.AST | None, *, annotation: bool) -> bool:
        return isinstance(node, ast.Call) and self._import_name(node.func, at, annotation=annotation) in {
            "fastapi.Security",
            "fastapi.param_functions.Security",
            "fastapi.params.Security",
        }

    def _import_name(self, expression: ast.expr, at: ast.AST | None, *, annotation: bool) -> str | None:
        root = expression
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name) or at is None:
            return None
        provenance = self._context.static_resource_provenance
        binding = provenance.binding(root.id, at) if annotation else provenance.runtime_binding(root.id, at)
        if not isinstance(binding, ast.alias):
            return None
        return import_name_for_binding(expression, binding, self._context.parents.get(binding))

    def _declares(self, node: ast.expr, depth: int) -> bool:
        if depth > _MAX_ALIAS_DEPTH:
            return False
        match node:
            case ast.Call():
                return self._is_security(node, node, annotation=False)
            case ast.List(elts=items) | ast.Tuple(elts=items) | ast.Set(elts=items):
                return any(self._declares(item, depth + 1) for item in items)
            case ast.Starred(value=value):
                return self._declares(value, depth + 1)
            case ast.BinOp(op=ast.Add(), left=left, right=right):
                return self._declares(left, depth + 1) or self._declares(right, depth + 1)
            case ast.Name(id=name):
                binding = self._context.static_resource_provenance.runtime_binding(name, node)
                if binding is None or binding in self._mutated:
                    return False
                value = self._bound_value(binding)
                return value is not None and self._declares(value, depth + 1)
            case _:
                return False

    def _bound_value(self, binding: ast.AST) -> ast.expr | None:
        statement = self._context.parents.get(binding)
        if not isinstance(binding, ast.Name) or not isinstance(statement, ast.Assign | ast.AnnAssign | ast.TypeAlias):
            return None
        if isinstance(statement, ast.Assign) and len(statement.targets) != 1:
            return None
        return statement.value
