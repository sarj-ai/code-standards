from __future__ import annotations

import ast
from functools import cached_property
from io import StringIO
import tokenize
from typing import TYPE_CHECKING, final

from sarj_rule_contracts import TextEdit

from sarj_python_lint._autofix_docs import private_unescaped_function
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


@final
class RepeatedLiteralFixes:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = ResourceProvenance(context)
        self.lines = StringIO(context.source, newline="").readlines()
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))
        self.comment_lines = {
            token.start[0]
            for token in tokenize.generate_tokens(StringIO(context.source, newline="").readline)
            if token.type == tokenize.COMMENT
        }

    @cached_property
    def locations(self) -> frozenset[tuple[int, int]]:
        return frozenset(
            (diagnostic.line, diagnostic.col)
            for diagnostic in REGISTRY["no-repeated-structured-string-literal"]().check_context(self.context)
        )

    def fixes(self, diagnostic: Diagnostic) -> list[TextEdit]:
        if diagnostic.code != "SARJ024":
            return []
        literals = {
            (node.lineno, node.col_offset + 1): node
            for node in self.context.nodes(ast.Constant)
            if isinstance(node.value, str)
        }
        literal = literals.get((diagnostic.line, diagnostic.col))
        if literal is None or (binding := self._binding(literal)) is None:
            return []
        group = [literals[location] for location in self.locations if literals[location].value == literal.value]
        if not group or any(self._binding(node) is not binding for node in group):
            return []
        name = ast.get_source_segment(self.context.source, binding)
        return [self._replace(node, name) for node in group] if name is not None else []

    def _binding(self, literal: ast.Constant) -> ast.Name | None:
        if not self._length_argument(literal):
            return None
        owner = self.provenance.scope(literal)
        parent = self.context.parents.get(owner) if owner is not None else None
        if (
            not isinstance(owner, ast.FunctionDef)
            or not isinstance(parent, ast.FunctionDef)
            or not private_unescaped_function(owner, self.context)
            or not self._plain_scopes(owner)
            or any(parent.lineno <= line <= (parent.end_lineno or parent.lineno) for line in self.comment_lines)
        ):
            return None
        candidates = [
            statement.targets[0]
            for statement in parent.body
            if isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Constant)
            and statement.value.value == literal.value
            and statement.lineno < owner.lineno
            and self._stable_binding(statement.targets[0], literal, parent)
            and self._already_shared(statement.targets[0], parent)
        ]
        return candidates[0] if len(candidates) == 1 else None

    def _length_argument(self, literal: ast.Constant | ast.Name) -> bool:
        call = self.context.parents.get(literal)
        return (
            isinstance(call, ast.Call)
            and call.args == [literal]
            and not call.keywords
            and isinstance(call.func, ast.Name)
            and call.func.id == "len"
            and self.context.imports.builtin_is_unshadowed("len")
            and self.provenance.builtin_namespace_untouched
            and self._unbound_len(call)
        )

    def _unbound_len(self, call: ast.Call) -> bool:
        scope = self.provenance.scope(call)
        while scope is not None:
            if "len" in self.provenance.bindings.get(scope, {}):
                return False
            scope = self.provenance.scope(scope)
        return True

    def _plain_scopes(self, owner: ast.FunctionDef) -> bool:
        scope: ast.AST | None = owner
        while scope is not None:
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and scope.type_params:
                return False
            scope = self.context.parents.get(scope)
        return True

    def _stable_binding(self, binding: ast.Name, literal: ast.Constant, parent: ast.FunctionDef) -> bool:
        return (
            self.provenance.bindings.get(parent, {}).get(binding.id) == [binding]
            and self.provenance.binding(binding.id, literal) is binding
            and binding.id not in self.provenance.external_bindings
            and (binding.lineno, binding.col_offset + 1) not in self.locations
        )

    def _already_shared(self, binding: ast.Name, parent: ast.FunctionDef) -> bool:
        for read in self.provenance.reads.get(binding.id, ()):
            owner = self.provenance.scope(read)
            if (
                self.provenance.binding(binding.id, read) is not binding
                or not self._length_argument(read)
                or not isinstance(owner, ast.FunctionDef)
            ):
                continue
            if (
                self.context.parents.get(owner) is parent
                and self._plain_scopes(owner)
                and private_unescaped_function(owner, self.context)
            ):
                return True
        return False

    def _replace(self, literal: ast.Constant, name: str) -> TextEdit:
        start = self._offset(literal.lineno, literal.col_offset)
        end = self._offset(literal.end_lineno or literal.lineno, literal.end_col_offset or literal.col_offset)
        newlines = "".join(
            "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else "\r" if line.endswith("\r") else ""
            for line in self.context.source[start:end].splitlines(keepends=True)
        )
        return TextEdit(start, end, name + newlines)

    def _offset(self, line: int, column: int) -> int:
        return self.starts[line - 1] + len(self.lines[line - 1].encode("utf-8")[:column].decode("utf-8"))
