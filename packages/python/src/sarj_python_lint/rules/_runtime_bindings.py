from __future__ import annotations

import ast
from collections import defaultdict
import symtable
from typing import TYPE_CHECKING, final


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sarj_python_lint._file_context import PythonFileContext


@final
class RuntimeBindings:
    def __init__(
        self, context: PythonFileContext, bindings: Mapping[ast.AST | None, Mapping[str, Sequence[ast.AST]]]
    ) -> None:
        self.bindings = bindings
        self.tables: dict[int, symtable.SymbolTable] = {}
        self.parents: dict[int, int | None] = {}
        self.by_scope: dict[ast.AST, int] = {}
        self.scopes: dict[int, ast.AST] = {}
        self.mutable: set[tuple[int, str]] = set()
        self.module: int | None = None
        tree = context.tree
        if tree is None:
            return
        try:
            root = symtable.symtable(context.source, str(context.path), "exec")
        except SyntaxError, UnicodeError, RecursionError:
            return
        self.module = root.get_id()
        self._collect(root)
        self._map_scopes(context, tree, root)
        self._index_writes()

    def lookup(self, scope: ast.AST | None, name: str) -> Sequence[ast.AST] | None:
        if scope is None or (table_id := self.by_scope.get(scope)) is None:
            return None
        symbol = _symbol(self.tables[table_id], name)
        if symbol is None or (owner := self._owner(table_id, symbol)) is None or (owner, name) in self.mutable:
            return None
        owner_scope = self.scopes.get(owner)
        return self.bindings.get(owner_scope, {}).get(name) if owner_scope is not None else None

    def _collect(self, root: symtable.SymbolTable) -> None:
        pending: list[tuple[symtable.SymbolTable, int | None]] = [(root, None)]
        while pending:
            table, parent = pending.pop()
            identity = table.get_id()
            self.tables[identity] = table
            self.parents[identity] = parent
            pending.extend((child, identity) for child in table.get_children())

    def _map_scopes(self, context: PythonFileContext, tree: ast.Module, root: symtable.SymbolTable) -> None:
        candidates: dict[tuple[symtable.SymbolTableType, str, int], list[int]] = defaultdict(list)
        for identity, table in self.tables.items():
            candidates[table.get_type(), table.get_name(), table.get_lineno()].append(identity)
        self.by_scope[tree] = root.get_id()
        self.scopes[root.get_id()] = tree
        for node in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef):
            kind = (
                symtable.SymbolTableType.CLASS if isinstance(node, ast.ClassDef) else symtable.SymbolTableType.FUNCTION
            )
            matches = candidates.get((kind, node.name, node.lineno), ())
            if len(matches) == 1:
                [identity] = matches
                self.by_scope[node] = identity
                self.scopes[identity] = node

    def _index_writes(self) -> None:
        for identity, table in self.tables.items():
            if identity == self.module:
                continue
            for symbol in table.get_symbols():
                if not (symbol.is_global() or symbol.is_nonlocal()):
                    continue
                if not (symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()):
                    continue
                owner = self._owner(identity, symbol)
                if owner is not None:
                    self.mutable.add((owner, symbol.get_name()))

    def _owner(self, identity: int, symbol: symtable.Symbol) -> int | None:
        if symbol.is_global():
            return self.module
        if symbol.is_local():
            return identity
        if not symbol.is_free():
            return None
        parent = self.parents.get(identity)
        while parent is not None:
            table = self.tables[parent]
            if table.get_type() is symtable.SymbolTableType.MODULE:
                break
            if table.get_type() is symtable.SymbolTableType.CLASS and symbol.get_name() == "__class__":
                # The compiler binds this cell to the lexically defined class.
                return None
            if table.get_type() is not symtable.SymbolTableType.CLASS:
                ancestor = _symbol(table, symbol.get_name())
                if ancestor is not None and ancestor.is_local():
                    return parent
            parent = self.parents.get(parent)
        return None


def _symbol(table: symtable.SymbolTable, name: str) -> symtable.Symbol | None:
    try:
        return table.lookup(name)
    except KeyError:
        return None
