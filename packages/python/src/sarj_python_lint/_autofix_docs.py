from __future__ import annotations

import ast
from functools import cached_property
from io import BytesIO, StringIO
import re
import tokenize
from typing import TYPE_CHECKING, final

from sarj_rule_contracts import TextEdit

from sarj_python_lint._autofix_inert import inert_private_scope
from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules import REGISTRY
from sarj_python_lint.rules._closed_helpers import dynamic_namespace
from sarj_python_lint.rules._comments import has_legal_notice
from sarj_python_lint.rules._docstrings import ARG_SECTIONS, docstring_expression, section_ranges
from sarj_python_lint.rules._prose_budget import groups
from sarj_python_lint.rules.no_unnecessary_docstring import module_docstring_may_escape


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
_FRAME_NAMES = frozenset(
    {
        "_getframe",
        "currentframe",
        "getouterframes",
        "getinnerframes",
        "stack",
        "get_stack",
        "getframeinfo",
        "getargvalues",
        "getgeneratorlocals",
        "getcoroutinelocals",
        "getasyncgenlocals",
        "_current_frames",
        "walk_stack",
        "walk_tb",
        "setprofile",
        "settrace",
        "setprofile_all_threads",
        "settrace_all_threads",
        "monitoring",
        "register_callback",
        "f_locals",
        "f_globals",
        "f_builtins",
        "f_back",
        "f_code",
        "tb_frame",
        "gi_frame",
        "cr_frame",
        "ag_frame",
        "__code__",
        "__closure__",
        "__defaults__",
        "__kwdefaults__",
        "__annotations__",
        "__doc__",
    }
)
_ARGUMENT_LABEL = re.compile(r"^[ \t]*\*{0,2}[A-Za-z_]\w*(?P<label>[ \t]*\([^)]+\))[ \t]*:")
_RESULT_LABEL = re.compile(r"^(?P<indent>[ \t]*)[^:]+:[ \t]*(?P<description>.*?)(?P<newline>\r?\n)?$")


def frame_metadata_observed(context: PythonFileContext) -> bool:
    return (
        any(node.attr in _FRAME_NAMES for node in context.nodes(ast.Attribute))
        or any(node.id in _FRAME_NAMES for node in context.nodes(ast.Name))
        or any(node.name in _FRAME_NAMES for node in context.nodes(ast.alias))
        or any(isinstance(node.value, str) and node.value in _FRAME_NAMES for node in context.nodes(ast.Constant))
    )


def private_unescaped_function(owner: _Function, context: PythonFileContext) -> bool:
    parent = context.parents.get(owner)
    if not owner.name.startswith("_") or not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    if (
        not isinstance(owner, ast.FunctionDef)
        or owner.decorator_list
        or dynamic_namespace(context)
        or frame_metadata_observed(context)
        or any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in ast.walk(owner))
    ):
        return False
    if not _ordinary_containing_callables(parent, context):
        return False
    declarations = [
        node for node in context.nodes(ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef) if node.name == owner.name
    ]
    return (
        declarations == [owner] and _closed_references(owner, parent, context) and inert_private_scope(owner, context)
    )


def _ordinary_containing_callables(parent: _Function, context: PythonFileContext) -> bool:
    ancestor: ast.AST | None = parent
    while ancestor is not None:
        if isinstance(ancestor, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            not isinstance(ancestor, ast.FunctionDef)
            or ancestor.decorator_list
            or any(
                isinstance(node, (ast.Yield, ast.YieldFrom, ast.GeneratorExp, ast.AsyncFunctionDef))
                for node in ast.walk(ancestor)
            )
        ):
            return False
        ancestor = context.parents.get(ancestor)
    return True


def _closed_references(owner: _Function, parent: _Function, context: PythonFileContext) -> bool:
    for node in context.nodes(ast.Name, ast.arg, ast.Global, ast.Nonlocal):
        match node:
            case ast.arg(arg=name) if name == owner.name:
                return False
            case ast.Global(names=names) | ast.Nonlocal(names=names) if owner.name in names:
                return False
            case ast.Name(id=name) if name == owner.name:
                if not _direct_enclosing_call(node, owner, parent, context):
                    return False
            case _:
                continue
    return True


def _direct_enclosing_call(
    reference: ast.Name, owner: _Function, parent: _Function, context: PythonFileContext
) -> bool:
    call = context.parents.get(reference)
    if not isinstance(reference.ctx, ast.Load) or not isinstance(call, ast.Call) or call.func is not reference:
        return False
    scope = context.parents.get(call)
    while scope is not None and scope is not owner and scope is not parent:
        if isinstance(
            scope,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.Lambda,
                ast.ListComp,
                ast.SetComp,
                ast.DictComp,
                ast.GeneratorExp,
            ),
        ):
            return False
        scope = context.parents.get(scope)
    return True


@final
class DocstringFixes:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.lines = StringIO(context.source, newline="").readlines()
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))

    @cached_property
    def unconsumed(self) -> frozenset[tuple[int, int]]:
        return frozenset(
            (diagnostic.line, diagnostic.col)
            for diagnostic in REGISTRY["no-unnecessary-docstring"]().check_context(self.context)
        )

    @cached_property
    def redundant(self) -> frozenset[tuple[int, int]]:
        return frozenset(
            (diagnostic.line, diagnostic.col)
            for diagnostic in REGISTRY["redundant-docstring"]().check_context(self.context)
            if diagnostic.severity is Severity.ERROR
        )

    def fixes(self, diagnostic: Diagnostic) -> list[TextEdit]:
        if diagnostic.code in {"SARJ099", "SARJ420"}:
            module_edits = self._module(diagnostic)
            if module_edits:
                return module_edits
        return self._function(diagnostic)

    def _function(self, diagnostic: Diagnostic) -> list[TextEdit]:
        for owner in self.context.nodes(ast.FunctionDef, ast.AsyncFunctionDef):
            if not owner.body or not private_unescaped_function(owner, self.context):
                continue
            expression = owner.body[0]
            if not isinstance(expression, ast.Expr) or self._literal(expression) is None:
                continue
            location = (expression.lineno, expression.col_offset + 1)
            if location not in self.unconsumed or not expression.lineno <= diagnostic.line <= (
                expression.end_lineno or expression.lineno
            ):
                continue
            if diagnostic.code in {"SARJ050", "SARJ420"}:
                return self._remove(owner, expression) if location in self.redundant else []
            if diagnostic.code in {"SARJ086", "SARJ087"}:
                return self._sections(owner, expression, diagnostic)
            return self._labels(expression, diagnostic)
        return []

    def _module(self, diagnostic: Diagnostic) -> list[TextEdit]:
        tree = self.context.tree
        if tree is None or not tree.body:
            return []
        expression = docstring_expression(tree)
        if expression is None:
            return []
        if (
            (expression.lineno, expression.col_offset + 1) not in self.unconsumed
            or diagnostic.line != expression.lineno
            or self._standalone(expression) is None
        ):
            return []
        if (
            dynamic_namespace(self.context)
            or frame_metadata_observed(self.context)
            or any(node.attr == "modules" for node in self.context.nodes(ast.Attribute))
            or any(node.attr == "import_module" for node in self.context.nodes(ast.Attribute))
            or any(node.name == "import_module" for node in self.context.nodes(ast.alias))
        ):
            return []
        if module_docstring_may_escape(self.context):
            return []
        if has_legal_notice(ast.get_docstring(tree, clean=False) or ""):
            return []
        if not self._module_header_preserved(expression):
            return []
        return self._remove(tree, expression)

    def _module_header_preserved(self, expression: ast.Expr) -> bool:
        end_line = expression.end_lineno or expression.lineno
        if any(
            token.type == tokenize.COMMENT and expression.lineno <= token.start[0] <= end_line
            for token in tokenize.generate_tokens(StringIO(self.context.source, newline="").readline)
        ):
            return False
        original = self.context.source
        candidate = original[: self.starts[expression.lineno - 1]] + original[self.starts[end_line] :]
        if candidate.startswith("#!") != original.startswith("#!"):
            return False
        try:
            original_encoding = tokenize.detect_encoding(BytesIO(original.encode("utf-8")).readline)[0]
            candidate_encoding = tokenize.detect_encoding(BytesIO(candidate.encode("utf-8")).readline)[0]
        except SyntaxError, LookupError:
            return False
        return original_encoding == candidate_encoding

    def _literal(self, expression: ast.Expr) -> tuple[int, int, str] | None:
        bounds = self._standalone(expression)
        if bounds is None:
            return None
        start, end = bounds
        literal = self.context.source[start:end]
        if literal[:3] not in {'"""', "'''"} or literal[-3:] != literal[:3] or "\\" in literal:
            return None
        return start, end, literal

    def _standalone(self, expression: ast.Expr) -> tuple[int, int] | None:
        end_line = expression.end_lineno
        end_column = expression.end_col_offset
        if end_line is None or end_column is None:
            return None
        start = self._offset(expression.lineno, expression.col_offset)
        end = self._offset(end_line, end_column)
        if self.context.source[self.starts[expression.lineno - 1] : start].strip():
            return None
        if self.context.source[end : self.starts[end_line]].strip():
            return None
        return start, end

    def _offset(self, line: int, byte_column: int) -> int:
        return self.starts[line - 1] + len(self.lines[line - 1].encode("utf-8")[:byte_column].decode("utf-8"))

    def _remove(self, owner: ast.Module | _Function, expression: ast.Expr) -> list[TextEdit]:
        if not owner.body[1:] and not isinstance(owner, ast.Module):
            return []
        if (
            len(owner.body) > 1
            and isinstance(owner.body[1], ast.Expr)
            and isinstance(owner.body[1].value, ast.Constant)
            and isinstance(owner.body[1].value.value, str)
        ):
            return []
        end_line = expression.end_lineno or expression.lineno
        return [TextEdit(self.starts[expression.lineno - 1], self.starts[end_line], "")]

    def _sections(self, owner: _Function, expression: ast.Expr, diagnostic: Diagnostic) -> list[TextEdit]:
        value = expression.value
        literal = self._literal(expression)
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str) or literal is None:
            return []
        wanted = (
            frozenset(ARG_SECTIONS)
            if diagnostic.code == "SARJ086"
            else frozenset({"Returns", "Return", "Yields", "Yield"})
        )
        ranges = [(start, end) for name, start, end in section_ranges(value.value) if name in wanted]
        # Other section headings may carry independent contracts; only the detector-owned heading can be removed.
        if len(ranges) != 1:
            return []
        document = value.value
        for start, end in reversed(ranges):
            document = document[:start] + document[end:]
        if not document.strip():
            return self._remove(owner, expression)
        quote = literal[2][:3]
        newline = "\r\n" if "\r\n" in literal[2] else "\n"
        document = document.rstrip() + "\n" + " " * expression.col_offset
        replacement = quote + document.replace("\n", newline) + quote
        return [TextEdit(literal[0], literal[1], replacement)]

    def _labels(self, expression: ast.Expr, diagnostic: Diagnostic) -> list[TextEdit]:
        for group in groups(self.context.path, self.context.source):
            if group.line != expression.lineno or diagnostic.line not in group.typed_restatements:
                continue
            edits: list[TextEdit] = []
            for line in group.typed_restatements:
                original = self.lines[line - 1]
                if argument := _ARGUMENT_LABEL.match(original):
                    start, end = argument.span("label")
                    edits.append(TextEdit(self.starts[line - 1] + start, self.starts[line - 1] + end, ""))
                elif result := _RESULT_LABEL.match(original):
                    replacement = result["indent"] + result["description"] + (result["newline"] or "")
                    edits.append(TextEdit(self.starts[line - 1], self.starts[line], replacement))
            return edits
        return []
