from __future__ import annotations

import ast
from functools import cached_property
from io import StringIO
import tokenize
from typing import TYPE_CHECKING, final

from sarj_rule_contracts import TextEdit

from sarj_python_lint._autofix_parameters import ParameterFixes
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


@final
class DeclaredContractFixes:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = ResourceProvenance(context)
        self.parameters = ParameterFixes(context)
        self.lines = StringIO(context.source, newline="").readlines()
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))

    def fixes(self, diagnostic: Diagnostic) -> list[TextEdit]:
        return self.plans.get((diagnostic.code, diagnostic.line, diagnostic.col), [])

    @cached_property
    def plans(self) -> dict[tuple[str, int, int], list[TextEdit]]:
        result: dict[tuple[str, int, int], list[TextEdit]] = {}
        if self.context.tree is None:
            return result
        for owner in self.context.nodes(ast.FunctionDef):
            annotation = self._precise_return(owner)
            if annotation is not None:
                edit = self._replace(annotation, "str")
                if edit is not None:
                    result["SARJ528", annotation.lineno, annotation.col_offset + 1] = [edit]
        return result

    def _precise_return(self, owner: ast.FunctionDef) -> ast.Name | None:
        annotation = owner.returns
        if (
            not isinstance(annotation, ast.Name)
            or annotation.id != "object"
            or not self._builtin("object")
            or not self._builtin("str")
            or not _no_arguments(owner)
        ):
            return None
        if (
            len(owner.body) != 1
            or not isinstance(owner.body[0], ast.Return)
            or not isinstance(owner.body[0].value, ast.Constant)
            or type(owner.body[0].value.value) is not str
        ):
            return None
        calls = self.parameters.closed_calls(owner)
        if not calls or any(
            call.args
            or call.keywords
            or not isinstance(parent := self.context.parents.get(call), ast.If)
            or parent.test is not call
            for call in calls
        ):
            return None
        parent = self.context.parents.get(owner)
        while parent is not None:
            if isinstance(parent, ast.FunctionDef) and parent.returns is None:
                return None
            parent = self.context.parents.get(parent)
        return annotation

    def _builtin(self, name: str) -> bool:
        return (
            self.context.imports.builtin_is_unshadowed(name)
            and self.provenance.builtin_namespace_untouched
            and all(name not in bindings for bindings in self.provenance.bindings.values())
        )

    def _replace(self, node: ast.expr, replacement: str) -> TextEdit | None:
        if node.lineno != node.end_lineno or node.end_col_offset is None:
            return None
        start = self.starts[node.lineno - 1] + len(
            self.lines[node.lineno - 1].encode("utf-8")[: node.col_offset].decode("utf-8")
        )
        end = self.starts[node.lineno - 1] + len(
            self.lines[node.lineno - 1].encode("utf-8")[: node.end_col_offset].decode("utf-8")
        )
        if any(
            token.type == tokenize.COMMENT
            for token in tokenize.generate_tokens(StringIO(self.context.source[start:end], newline="").readline)
        ):
            return None
        return TextEdit(start, end, replacement)


def _no_arguments(owner: ast.FunctionDef) -> bool:
    args = owner.args
    return not (args.posonlyargs or args.args or args.kwonlyargs or args.vararg or args.kwarg or args.defaults)
