from __future__ import annotations

import ast
from collections import defaultdict
from typing import TYPE_CHECKING, final


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext


_SCOPES = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


@final
class ResourceProvenance:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.bindings: dict[ast.AST | None, dict[str, list[ast.AST]]] = defaultdict(lambda: defaultdict(list))
        self.reads: dict[str, list[ast.Name]] = defaultdict(list)
        self.escape_cache: dict[tuple[ast.AST, bool], bool] = {}
        self.wildcard = False
        self.mutated: set[str] = set()
        for node in context.nodes(ast.AST):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                self.reads[node.id].append(node)

            for name in _bound_names(node):
                self.bindings[self.scope(node)][name].append(node)
                self.wildcard |= name == "*"
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store | ast.Del):
                root = _root_name(node)
                if root is not None:
                    self.mutated.add(root)

    def scope(self, node: ast.AST) -> ast.AST | None:
        parent = self.context.parents.get(node)
        while parent is not None and not isinstance(parent, _SCOPES):
            parent = self.context.parents.get(parent)
        return parent

    def binding(self, name: str, at: ast.AST) -> ast.AST | None:
        scope = self.scope(at)
        while scope is not None:
            nodes = self.bindings.get(scope, {}).get(name)
            if nodes:
                return nodes[0] if len(nodes) == 1 else None
            scope = self.scope(scope)
        return None

    def imported(self, node: ast.expr, qualified: str) -> bool:
        root = _root_name(node)
        if self.wildcard or root is None or root in self.mutated:
            return False
        binding = self.binding(root, node)
        for read in self.reads.get(root, ()):
            parent = self.context.parents.get(read)
            if isinstance(parent, ast.Attribute | ast.ExceptHandler):
                continue
            if not (isinstance(parent, ast.Call) and parent.func is read):
                return False
        return (
            isinstance(binding, ast.alias)
            and isinstance(self.scope(binding), ast.Module)
            and self.context.imports.resolved_qualified_name(node) == qualified
        )

    def constructor(self, name: ast.Name, at: ast.AST) -> ast.Call | None:
        binding = self.binding(name.id, at)
        if not isinstance(binding, ast.Name):
            return None
        statement = self.context.parents.get(binding)
        if isinstance(statement, ast.withitem):
            owner = self.context.parents.get(statement)
            if (
                binding is statement.optional_vars
                and self.contains(owner, at)
                and isinstance(statement.context_expr, ast.Call)
            ):
                return statement.context_expr
            return None
        value = self.assignment_value(binding, at)
        return value if isinstance(value, ast.Call) else None

    def assignment_value(self, binding: ast.Name, at: ast.AST) -> ast.expr | None:
        statement = self.context.parents.get(binding)
        if not isinstance(statement, ast.Assign | ast.AnnAssign):
            return None
        if isinstance(statement, ast.Assign) and len(statement.targets) != 1:
            return None
        if not isinstance(self.context.parents.get(statement), ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
            return None
        return statement.value if statement.lineno < getattr(at, "lineno", 0) else None

    def async_function(self, value: ast.expr, at: ast.AST) -> ast.AsyncFunctionDef | None:
        seen: set[str] = set()
        while isinstance(value, ast.Name) and value.id not in seen:
            seen.add(value.id)
            if value.id in self.mutated:
                return None
            binding = self.binding(value.id, at)
            if isinstance(binding, ast.AsyncFunctionDef):
                owner = self.context.parents.get(binding)
                if not isinstance(owner, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef):
                    return None
                if binding.decorator_list or any(
                    isinstance(node, ast.Yield | ast.YieldFrom) for node in ast.walk(binding)
                ):
                    return None
                return binding
            if not isinstance(binding, ast.Name):
                return None
            resolved = self.assignment_value(binding, at)
            if resolved is None:
                return None
            value, at = resolved, binding
        return None

    def unescaped(self, name: ast.Name, at: ast.AST, *, allow_context: bool = False) -> bool:
        binding = self.binding(name.id, at)
        if binding is None or name.id in self.mutated:
            return False
        key = (binding, allow_context)
        if key not in self.escape_cache:
            self.escape_cache[key] = all(
                self._method_or_context_read(read, allow_context=allow_context)
                for read in self.reads.get(name.id, ())
                if self.binding(read.id, read) is binding
            )
        return self.escape_cache[key]

    def _method_or_context_read(self, read: ast.Name, *, allow_context: bool) -> bool:
        parent = self.context.parents.get(read)
        if allow_context and isinstance(parent, ast.withitem) and parent.context_expr is read:
            return True
        if not isinstance(parent, ast.Attribute) or parent.value is not read:
            return False
        call = self.context.parents.get(parent)
        return isinstance(call, ast.Call) and call.func is parent

    def contains(self, owner: ast.AST | None, node: ast.AST) -> bool:
        while node in self.context.parents:
            node = self.context.parents[node]
            if node is owner:
                return True
        return False


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _bound_names(node: ast.AST) -> tuple[str, ...]:
    match node:
        case ast.Name(id=name, ctx=ast.Store() | ast.Del()) | ast.arg(arg=name):
            return (name,)
        case ast.alias():
            return (node.asname or node.name.partition(".")[0],)
        case (
            ast.FunctionDef(name=name)
            | ast.AsyncFunctionDef(name=name)
            | ast.ClassDef(name=name)
            | ast.ExceptHandler(name=str() as name)
            | ast.MatchAs(name=str() as name)
            | ast.MatchStar(name=str() as name)
            | ast.MatchMapping(rest=str() as name)
        ):
            return (name,)
        case ast.Global(names=names) | ast.Nonlocal(names=names):
            return tuple(names)
        case _:
            return ()
