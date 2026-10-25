from __future__ import annotations

import ast
from functools import cached_property
from io import StringIO
import tokenize
from typing import TYPE_CHECKING, final
from unicodedata import normalize

from sarj_rule_contracts import TextEdit

from sarj_python_lint._autofix_parameters import ParameterFixes
from sarj_python_lint.rules import REGISTRY


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


@final
class AliasFixes:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.parameters = ParameterFixes(context)
        self.lines = StringIO(context.source, newline="").readlines()
        self.tokens = list(tokenize.generate_tokens(StringIO(context.source, newline="").readline))
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))

    @cached_property
    def _native_locations(self) -> frozenset[tuple[int, int]]:
        return frozenset(
            (finding.line, finding.col)
            for finding in REGISTRY["no-redundant-local-alias"]().check_context(self.context)
        )

    def fixes(self, diagnostic: Diagnostic) -> list[TextEdit]:
        if diagnostic.code != "SARJ531" or self.context.tree is None or self.context.generated:
            return []
        if (diagnostic.line, diagnostic.col) not in self._native_locations:
            return []
        for owner in self.context.nodes(ast.FunctionDef):
            profile = self._profile(owner)
            if profile is None:
                continue
            assignment, target, use = profile
            if (target.lineno, target.col_offset + 1) == (diagnostic.line, diagnostic.col):
                return self._edits(owner, assignment, target, use)
        return []

    def _profile(self, owner: ast.FunctionDef) -> tuple[ast.Assign, ast.Name, ast.Name] | None:
        args = owner.args
        if owner.returns is not None or owner.type_comment is not None or owner.type_params:
            return None
        if args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg or args.defaults:
            return None
        if args.kw_defaults or len(args.args) != 1 or args.args[0].annotation is not None:
            return None
        if owner.name.startswith("__") or not self._builtin_dict():
            return None
        match owner.body:
            case [
                ast.Assign(targets=[ast.Name() as target], value=ast.Name() as source) as assignment,
                ast.Return(value=ast.Call(func=ast.Name(id="dict"), args=[], keywords=[keyword])),
            ]:
                if source.id != args.args[0].arg or target.id == source.id or assignment.type_comment is not None:
                    return None
                if keyword.arg != target.id or not isinstance(keyword.value, ast.Name):
                    return None
                if keyword.value.id != target.id or not self.parameters.closed_calls(owner):
                    return None
                return assignment, target, keyword.value
            case _:
                return None

    def _builtin_dict(self) -> bool:
        provenance = self.parameters.provenance
        return (
            self.context.imports.builtin_is_unshadowed("dict")
            and provenance.builtin_namespace_untouched
            and all("dict" not in bindings for bindings in provenance.bindings.values())
        )

    def _offset(self, line: int, column: int) -> int:
        return self.starts[line - 1] + len(self.lines[line - 1].encode("utf-8")[:column].decode("utf-8"))

    def _edits(self, owner: ast.FunctionDef, assignment: ast.Assign, target: ast.Name, use: ast.Name) -> list[TextEdit]:
        end_line = owner.end_lineno
        assignment_end = assignment.end_lineno
        if end_line is None or assignment_end is None or assignment.end_col_offset is None:
            return []
        if any(
            part.type == tokenize.COMMENT or (part.type == tokenize.OP and part.string == ";")
            for part in self.tokens
            if owner.lineno <= part.start[0] <= end_line
        ):
            return []
        line_start = self.starts[assignment.lineno - 1]
        start = self._offset(assignment.lineno, assignment.col_offset)
        end = self._offset(assignment_end, assignment.end_col_offset)
        line_end = self.starts[assignment_end]
        if self.context.source[line_start:start].strip() or self.context.source[end:line_end].strip():
            return []
        source = assignment.value
        if not isinstance(source, ast.Name):
            return []
        raw_source = self._raw_name(source, source.id)
        raw_use = self._raw_name(use, target.id)
        if raw_source is None or raw_use is None:
            return []
        use_start = self._offset(use.lineno, use.col_offset)
        use_end = use_start + len(raw_use)
        return [TextEdit(line_start, line_end, ""), TextEdit(use_start, use_end, raw_source)]

    def _raw_name(self, node: ast.Name, expected: str) -> str | None:
        if node.end_lineno != node.lineno or node.end_col_offset is None:
            return None
        start = self._offset(node.lineno, node.col_offset)
        end = self._offset(node.lineno, node.end_col_offset)
        raw = self.context.source[start:end]
        return raw if raw.isidentifier() and normalize("NFKC", raw) == expected else None
