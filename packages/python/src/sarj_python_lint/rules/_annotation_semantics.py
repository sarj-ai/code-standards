from __future__ import annotations

import ast
from dataclasses import dataclass
from types import MappingProxyType
from typing import NamedTuple, Self

from sarj_python_lint.rules._imports import ImportIndex


_TYPING_SOURCES = frozenset({"typing", "typing_extensions"})
_TRANSPARENT_WRAPPERS = frozenset({"Annotated", "ClassVar", "Final", "NotRequired", "Optional", "ReadOnly", "Required"})


def bit_or_members(expression: ast.expr) -> list[ast.expr]:
    members: list[ast.expr] = []
    pending = [expression]
    while pending:
        member = pending.pop()
        if isinstance(member, ast.BinOp) and isinstance(member.op, ast.BitOr):
            pending.extend((member.right, member.left))
        else:
            members.append(member)
    return members


class _AnnotationMember(NamedTuple):
    node: ast.expr | None
    seen: frozenset[str]


@dataclass(frozen=True, slots=True)
class AnnotationSemantics:
    imports: ImportIndex
    aliases: MappingProxyType[str, ast.expr]

    @classmethod
    def from_tree(cls, tree: ast.Module, *, module_scope_only: bool = True) -> Self:
        return cls.from_imports(tree, ImportIndex.from_tree(tree, module_scope_only=module_scope_only))

    @classmethod
    def from_imports(cls, tree: ast.Module, imports: ImportIndex) -> Self:
        candidates: dict[str, ast.expr] = {}
        ambiguous: set[str] = set()
        for statement in tree.body:
            name: str | None = None
            value: ast.expr | None = None
            match statement:
                case ast.TypeAlias(name=ast.Name(id=alias), value=alias_value, type_params=[]):
                    name, value = alias, alias_value
                case ast.AnnAssign(target=ast.Name(id=alias), annotation=annotation, value=alias_value) if (
                    alias_value is not None
                    and imports.resolves(annotation, sources=_TYPING_SOURCES, symbol="TypeAlias")
                ):
                    name, value = alias, alias_value
                case _:
                    pass
            if name is None or value is None:
                continue
            if name in candidates:
                ambiguous.add(name)
            else:
                candidates[name] = value
        if not candidates:
            return cls(imports, MappingProxyType({}))
        rebound = _module_rebindings(tree)
        aliases = {name: value for name, value in candidates.items() if name not in ambiguous and name not in rebound}
        return cls(imports, MappingProxyType(aliases))

    @staticmethod
    def parse(annotation: ast.expr | None) -> ast.expr | None:
        if not isinstance(annotation, ast.Constant) or not isinstance(annotation.value, str):
            return annotation
        try:
            parsed = ast.parse(annotation.value.strip(), mode="eval").body
        except SyntaxError, UnicodeError:
            return None
        ast.copy_location(parsed, annotation)
        return parsed

    def resolve_alias(self, annotation: ast.expr | None, *, seen: frozenset[str] = frozenset()) -> ast.expr | None:
        resolved = self.parse(annotation)
        while isinstance(resolved, ast.Name) and resolved.id in self.aliases and resolved.id not in seen:
            seen |= {resolved.id}
            resolved = self.parse(self.aliases[resolved.id])
        return resolved

    def transparent_members(
        self, annotation: ast.expr | None, *, seen: frozenset[str] = frozenset()
    ) -> tuple[ast.expr, ...]:
        resolved = self.parse(annotation)
        if resolved is None:
            return ()
        if isinstance(resolved, ast.Name) and resolved.id in self.aliases:
            pending = [_AnnotationMember(resolved, seen)]
        else:
            children = self._transparent_children(resolved)
            if children is None:
                return (resolved,)
            pending = [_AnnotationMember(child, seen) for child in reversed(children)]
        members: list[ast.expr] = []
        while pending:
            state = self._resolve_member(pending.pop())
            if state.node is None:
                continue
            children = self._transparent_children(state.node)
            if children is None:
                members.append(state.node)
            else:
                pending.extend(_AnnotationMember(child, state.seen) for child in reversed(children))
        return tuple(members)

    def _resolve_member(self, state: _AnnotationMember) -> _AnnotationMember:
        node = self.parse(state.node)
        if not isinstance(node, ast.Name) or node.id not in self.aliases:
            return _AnnotationMember(node, state.seen)
        seen = set(state.seen)
        while isinstance(node, ast.Name) and node.id in self.aliases:
            if node.id in seen:
                return _AnnotationMember(None, frozenset(seen))
            seen.add(node.id)
            node = self.parse(self.aliases[node.id])
        return _AnnotationMember(node, frozenset(seen))

    def _transparent_children(self, node: ast.expr) -> list[ast.expr] | None:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return bit_or_members(node)
        if not isinstance(node, ast.Subscript):
            return None
        wrapper = self.imports.resolved_symbol(node.value, sources=_TYPING_SOURCES)
        if wrapper == "Union":
            return list(node.slice.elts) if isinstance(node.slice, ast.Tuple) else [node.slice]
        if wrapper not in _TRANSPARENT_WRAPPERS:
            return None
        if isinstance(node.slice, ast.Tuple):
            if not node.slice.elts:
                return None
            return [node.slice.elts[0]]
        return [node.slice]


def _module_rebindings(tree: ast.Module) -> set[str]:
    counts: dict[str, int] = {}
    for statement in tree.body:
        for name in _bound_names(statement):
            counts[name] = counts.get(name, 0) + 1
    return {name for name, count in counts.items() if count > 1}


def scope_bound_names(statements: list[ast.stmt]) -> set[str]:
    return {name for statement in statements for name in _bound_names(statement)}


def _bound_names(statement: ast.stmt) -> set[str]:
    collector = _ScopeBindings()
    collector.visit(statement)
    return collector.names


def _target_names(node: ast.expr) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.List, ast.Tuple)):
        return {name for item in node.elts for name in _target_names(item)}
    return set()


class _ScopeBindings(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()
        self._pending: list[ast.AST] = []

    def visit(self, node: ast.AST) -> None:
        self._pending.append(node)
        while self._pending:
            super().visit(self._pending.pop())

    def generic_visit(self, node: ast.AST) -> None:
        self._pending.extend(reversed(tuple(ast.iter_child_nodes(node))))

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.partition(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names if alias.name != "*")

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self.names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self.names.add(node.rest)
        self.generic_visit(node)
