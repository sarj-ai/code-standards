from __future__ import annotations

import ast
from io import StringIO
import tokenize
from typing import TYPE_CHECKING, final

from sarj_rule_contracts import TextEdit

from sarj_python_lint._autofix_parameters import ParameterFixes
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


_MAPPING_TYPE_ARGUMENTS = 2


@final
class AnnotationFixes:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.provenance = ResourceProvenance(context)
        self.parameters = ParameterFixes(context)

    def fixes(self, diagnostic: Diagnostic) -> list[TextEdit]:
        if diagnostic.code != "SARJ447" or not self._builtin_object():
            return []
        for argument in self.context.nodes(ast.arg):
            annotation = argument.annotation
            if (
                not isinstance(annotation, ast.Subscript)
                or (annotation.lineno, annotation.col_offset + 1) != (diagnostic.line, diagnostic.col)
                or not isinstance(annotation.slice, ast.Tuple)
                or len(annotation.slice.elts) != _MAPPING_TYPE_ARGUMENTS
            ):
                continue
            key, value = annotation.slice.elts
            if (
                not isinstance(key, ast.Name)
                or key.id != "str"
                or not self.context.imports.builtin_is_unshadowed("str")
            ):
                continue
            if (
                not self._imported(annotation.value, ("collections.abc.Mapping", "typing.Mapping"))
                or not self._imported(value, ("typing.Any", "typing_extensions.Any"))
                or not self._retained_import_use(value)
            ):
                continue
            arguments = self.context.parents.get(argument)
            owner = self.context.parents.get(arguments) if arguments is not None else None
            if not isinstance(owner, ast.FunctionDef) or not self._unused_parameter(owner, argument):
                continue
            return [self._replace(value)]
        return []

    def _builtin_object(self) -> bool:
        return (
            self.context.imports.builtin_is_unshadowed("object")
            and self.provenance.builtin_namespace_untouched
            and all("object" not in bindings for bindings in self.provenance.bindings.values())
        )

    def _imported(self, node: ast.expr, names: tuple[str, ...]) -> bool:
        root = node
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name) or self.context.imports.resolved_qualified_name(node) not in names:
            return False
        binding = self.provenance.binding(root.id, root)
        imported = self.context.parents.get(binding) if isinstance(binding, ast.alias) else None
        return (
            isinstance(imported, (ast.Import, ast.ImportFrom))
            and self.context.parents.get(imported) is self.context.tree
        )

    def _retained_import_use(self, value: ast.expr) -> bool:
        root = value
        while isinstance(root, ast.Attribute):
            root = root.value
        return isinstance(root, ast.Name) and any(
            node.id == root.id
            and node is not root
            and isinstance(node.ctx, ast.Load)
            and self.provenance.binding(node.id, node) is self.provenance.binding(root.id, root)
            for node in self.context.nodes(ast.Name)
        )

    def _unused_parameter(self, owner: ast.FunctionDef, argument: ast.arg) -> bool:
        if (
            owner.args.defaults
            or any(default is not None for default in owner.args.kw_defaults)
            or self.parameters.closed_calls(owner) is None
        ):
            return False
        if any(
            (isinstance(node, ast.Name) and node.id == argument.arg)
            or (isinstance(node, ast.Constant) and isinstance(node.value, str) and argument.arg in node.value)
            for node in ast.walk(owner)
        ):
            return False
        return not any(
            token.type == tokenize.COMMENT and owner.lineno <= token.start[0] <= (owner.end_lineno or owner.lineno)
            for token in tokenize.generate_tokens(StringIO(self.context.source, newline="").readline)
        )

    def _replace(self, node: ast.expr) -> TextEdit:
        lines = StringIO(self.context.source, newline="").readlines()
        starts = [0]
        for line in lines:
            starts.append(starts[-1] + len(line))
        end_line = node.end_lineno or node.lineno
        start = starts[node.lineno - 1] + len(lines[node.lineno - 1].encode("utf-8")[: node.col_offset].decode("utf-8"))
        end = starts[end_line - 1] + len(lines[end_line - 1].encode("utf-8")[: node.end_col_offset].decode("utf-8"))
        endings = "".join(
            "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else "\r" if line.endswith("\r") else ""
            for line in self.context.source[start:end].splitlines(keepends=True)
        )
        return TextEdit(start, end, "object" + endings)
