from __future__ import annotations

import ast
from functools import cached_property
from typing import TYPE_CHECKING, final

from sarj_python_lint._analysis_session import AnalysisSession
from sarj_python_lint._source import python_source_lines, symbol_prefilter_source
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics
from sarj_python_lint.rules._ast_index import NodeIndex
from sarj_python_lint.rules._binding_inventory import BindingInventory
from sarj_python_lint.rules._fastapi import FastapiIndex
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._namespace_access import dynamic_namespace_access
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._runtime_bindings import RuntimeBindings


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from sarj_python_lint.rules._copy_on_write import CopyOnWriteAnalysis
    from sarj_python_lint.rules._resource_provenance import ResourceProvenance
    from sarj_python_lint.rules._test_provenance import TestProvenance


@final  # ruff: ignore[too-many-public-methods] -- one file owns the lazy fact caches and their shared lifetime; splitting providers would duplicate semantic state.
class PythonFileContext:
    def __init__(self, path: Path, source: str, session: AnalysisSession | None = None) -> None:
        self.path = path
        self.source = source
        self.session = session if session is not None else AnalysisSession()

    @cached_property
    def symbol_source(self) -> str:
        return symbol_prefilter_source(self.source)

    @cached_property
    def tree(self) -> ast.Module | None:
        if self.session.project is not None:
            unit = self.session.project.unit(self.path)
            if unit is not None and unit.source == self.source:
                return unit.tree
        try:
            return ast.parse(self.source, filename=str(self.path))
        except SyntaxError, UnicodeError:
            return None

    @cached_property
    def source_lines(self) -> list[str]:
        return python_source_lines(self.source)

    @cached_property
    def generated(self) -> bool:
        return is_generated(self.path, self.source)

    @cached_property
    def node_index(self) -> NodeIndex:
        return NodeIndex(self._valid_tree())

    def nodes[NodeT: ast.AST](self, *types: type[NodeT]) -> list[NodeT]:
        return [node for node in self.node_index.query(types) if isinstance(node, types)]

    @cached_property
    def has_wildcard_import(self) -> bool:
        return any(alias.name == "*" for node in self.nodes(ast.ImportFrom) for alias in node.names)

    @cached_property
    def consumed_docstring_names(self) -> frozenset[str]:
        from sarj_python_lint.rules._docstrings import consumed_docstring_names  # ruff: ignore[import-outside-top-level] -- share runtime docstring analysis only when requested.

        return consumed_docstring_names(self._valid_tree(), node_index=self.node_index)

    @cached_property
    def docstring_node_ids(self) -> frozenset[int]:
        result: set[int] = set()
        for owner in self.nodes(ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef):
            if not owner.body or not isinstance(owner.body[0], ast.Expr):
                continue
            value = owner.body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                result.add(id(value))
        return frozenset(result)

    @property
    def parents(self) -> Mapping[ast.AST, ast.AST]:
        return self.node_index.parents

    @cached_property
    def binding_inventory(self) -> BindingInventory:
        return BindingInventory.from_context(self)

    @cached_property
    def runtime_bindings(self) -> RuntimeBindings:
        return RuntimeBindings(self, self.binding_inventory.bindings)

    @cached_property
    def imports(self) -> ImportIndex:
        return ImportIndex.from_tree(self._valid_tree())

    @cached_property
    def module_imports(self) -> ImportIndex:
        return ImportIndex.from_tree(self._valid_tree(), module_scope_only=True)

    @cached_property
    def annotation_semantics(self) -> AnnotationSemantics:
        return AnnotationSemantics.from_imports(self._valid_tree(), self.module_imports)

    @cached_property
    def dynamic_namespace(self) -> bool:
        return dynamic_namespace_access(self.nodes(ast.AST), self.imports, self.parents)

    @cached_property
    def fastapi(self) -> FastapiIndex:
        return FastapiIndex(self._valid_tree(), path=self.path)

    @cached_property
    def test_provenance(self) -> TestProvenance:
        from sarj_python_lint.rules._test_provenance import TestProvenance  # ruff: ignore[import-outside-top-level] — defer test analysis until requested

        return TestProvenance(self, borrow_context=True)

    def _valid_tree(self) -> ast.Module:
        tree = self.tree
        if tree is None:
            msg = "syntax-dependent facts require a successfully parsed source file"
            raise ValueError(msg)
        return tree

    @cached_property
    def copy_on_write(self) -> CopyOnWriteAnalysis:
        from sarj_python_lint.rules._copy_on_write import CopyOnWriteAnalysis  # ruff: ignore[import-outside-top-level] — share ownership analysis only when requested

        return CopyOnWriteAnalysis(self, borrow_context=True)

    @cached_property
    def resource_provenance(self) -> ResourceProvenance:
        from sarj_python_lint.rules._resource_provenance import ResourceProvenance  # ruff: ignore[import-outside-top-level] -- file-owned binding facts are lazy.

        # The owner caches this analysis; borrowing prevents a reference cycle.
        return ResourceProvenance(self, borrow_context=True)

    @cached_property
    def static_resource_provenance(self) -> ResourceProvenance:
        from sarj_python_lint.rules._resource_provenance import ResourceProvenance  # ruff: ignore[import-outside-top-level] -- keep static-namespace policy in a separate cached analysis.

        return ResourceProvenance(self, require_static_namespace=True, borrow_context=True)
