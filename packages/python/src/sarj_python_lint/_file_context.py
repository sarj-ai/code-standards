from __future__ import annotations

import ast
from functools import cached_property
from typing import TYPE_CHECKING, final

from sarj_python_lint._analysis_session import AnalysisSession
from sarj_python_lint.rules._ast_index import NodeIndex
from sarj_python_lint.rules._fastapi import FastapiIndex
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_generated


if TYPE_CHECKING:
    from pathlib import Path


@final
class PythonFileContext:
    def __init__(self, path: Path, source: str, session: AnalysisSession | None = None) -> None:
        self.path = path
        self.source = source
        self.session = session if session is not None else AnalysisSession()

    @cached_property
    def tree(self) -> ast.Module | None:
        if self.session.project is not None:
            unit = self.session.project.unit(self.path)
            if unit is not None and unit.source == self.source:
                return unit.tree
        try:
            return ast.parse(self.source, filename=str(self.path))
        except SyntaxError:
            return None

    @cached_property
    def source_lines(self) -> list[str]:
        return self.source.splitlines()

    @cached_property
    def generated(self) -> bool:
        return is_generated(self.path, self.source)

    @cached_property
    def node_index(self) -> NodeIndex:
        return NodeIndex(self._valid_tree())

    def nodes[NodeT: ast.AST](self, *types: type[NodeT]) -> list[NodeT]:
        return [node for node in self.node_index.query(types) if isinstance(node, types)]

    @cached_property
    def imports(self) -> ImportIndex:
        return ImportIndex.from_tree(self._valid_tree())

    @cached_property
    def module_imports(self) -> ImportIndex:
        return ImportIndex.from_tree(self._valid_tree(), module_scope_only=True)

    @cached_property
    def fastapi(self) -> FastapiIndex:
        return FastapiIndex(self._valid_tree(), path=self.path)

    def _valid_tree(self) -> ast.Module:
        tree = self.tree
        if tree is None:
            msg = "syntax-dependent facts require a successfully parsed source file"
            raise ValueError(msg)
        return tree
