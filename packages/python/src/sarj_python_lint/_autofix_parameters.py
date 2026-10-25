from __future__ import annotations

import ast
from io import StringIO
import tokenize
from typing import TYPE_CHECKING, NamedTuple, final

from sarj_rule_contracts import TextEdit

from sarj_python_lint._autofix_docs import private_unescaped_function
from sarj_python_lint.rules import (
    no_unused_underscored_keyword_parameter as unused_rule,
    unused_test_factory_option as factory_rule,
)
from sarj_python_lint.rules._closed_helpers import call_matches, direct_call
from sarj_python_lint.rules._resource_provenance import ResourceProvenance


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


_NESTED_SCOPES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


class _Part(NamedTuple):
    start: int
    end: int


def _singleton(value: ast.expr | None) -> bool:
    return isinstance(value, ast.Constant) and (value.value is None or isinstance(value.value, bool))


@final
class ParameterFixes:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.lines = StringIO(context.source, newline="").readlines()
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))
        self.tokens = list(tokenize.generate_tokens(StringIO(context.source, newline="").readline))
        self.provenance = ResourceProvenance(context)

    def closed_calls(self, function: ast.FunctionDef) -> list[ast.Call] | None:
        return self._calls(function) if self._closed(function) else None

    def fixes(self, diagnostic: Diagnostic) -> list[TextEdit]:
        if diagnostic.code == "SARJ034":
            return self._keyword_only(diagnostic)
        if diagnostic.code == "SARJ477":
            return self._capture(diagnostic)
        for function in self.context.nodes(ast.FunctionDef):
            if not self._closed(function):
                continue
            for argument, default in zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True):
                if (argument.lineno, argument.col_offset + 1) != (diagnostic.line, diagnostic.col):
                    continue
                return self._keyword_option(function, argument, default, diagnostic)
        return []

    def _keyword_option(
        self, function: ast.FunctionDef, argument: ast.arg, default: ast.expr | None, diagnostic: Diagnostic
    ) -> list[TextEdit]:
        if argument.annotation is not None or not _singleton(default):
            return []
        calls = self._calls(function)
        if not calls:
            return []
        edits = self._signature(function, argument)
        if not edits:
            return []
        if diagnostic.code == "SARJ475":
            if argument not in unused_rule.unused_keyword_parameters(self.context, function):
                return []
        else:
            body_edits = self._factory_body(function, argument, calls)
            if not body_edits:
                return []
            edits.extend(body_edits)
        call_edits = self._remove_keyword_arguments(argument, calls)
        return [] if call_edits is None else [*edits, *call_edits]

    def _remove_keyword_arguments(self, argument: ast.arg, calls: list[ast.Call]) -> list[TextEdit] | None:
        edits: list[TextEdit] = []
        for call in calls:
            keyword = next((item for item in call.keywords if item.arg == argument.arg), None)
            if keyword is None:
                continue
            if not _singleton(keyword.value) or self._comments(call.lineno, call.end_lineno or call.lineno):
                return None
            replacement = ast.Call(
                func=call.func, args=call.args, keywords=[item for item in call.keywords if item is not keyword]
            )
            edits.append(self._replace(call, ast.unparse(replacement)))
        return edits

    def _keyword_only(self, diagnostic: Diagnostic) -> list[TextEdit]:
        for function in self.context.nodes(ast.FunctionDef):
            if (function.lineno, function.col_offset + 1) != (diagnostic.line, diagnostic.col) or not self._closed(
                function
            ):
                continue
            if (
                not function.args.args
                or function.args.posonlyargs
                or function.args.kwonlyargs
                or function.args.defaults
                or self._comments(function.lineno, function.body[0].lineno)
            ):
                continue
            calls = self._calls(function)
            if not calls:
                return []
            argument = function.args.args[0]
            position = self._offset(argument.lineno, argument.col_offset)
            call_edits = self._keyword_call_edits(function, calls)
            return [] if call_edits is None else [TextEdit(position, position, "*, "), *call_edits]
        return []

    def _keyword_call_edits(self, function: ast.FunctionDef, calls: list[ast.Call]) -> list[TextEdit] | None:
        edits: list[TextEdit] = []
        for call in calls:
            if self._comments(call.lineno, call.end_lineno or call.lineno):
                return None
            if not call.args:
                continue
            replacement = ast.Call(
                func=call.func,
                args=[],
                keywords=[
                    ast.keyword(arg=parameter.arg, value=value)
                    for parameter, value in zip(function.args.args, call.args, strict=False)
                ]
                + call.keywords,
            )
            edits.append(self._replace(call, ast.unparse(replacement)))
        return edits

    def _capture(self, diagnostic: Diagnostic) -> list[TextEdit]:
        for function in self.context.nodes(ast.FunctionDef):
            argument = function.args.kwarg
            if (
                argument is None
                or (argument.lineno, argument.col_offset + 1) != (diagnostic.line, diagnostic.col)
                or not self._inert_capture_annotation(argument.annotation)
                or not self._closed(function, allow_keyword_capture=True)
            ):
                continue
            if any(
                isinstance(node, ast.Name) and node.id == argument.arg
                for statement in function.body
                for node in ast.walk(statement)
            ):
                return []
            if self._calls(function) is None:
                return []
            return self._signature(function, argument)
        return []

    def _inert_capture_annotation(self, annotation: ast.expr | None) -> bool:
        return annotation is None or (
            isinstance(annotation, ast.Name)
            and annotation.id == "object"
            and self.context.imports.builtin_is_unshadowed("object")
            and self.provenance.binding("object", annotation) is None
            and self.provenance.builtin_namespace_untouched
        )

    def _factory_body(self, function: ast.FunctionDef, argument: ast.arg, calls: list[ast.Call]) -> list[TextEdit]:
        candidate = factory_rule.autofix_invariant_keyword_option(self.context, function, argument)
        if candidate is None or not _singleton(candidate[0]):
            return []
        value, native_calls = candidate
        if set(native_calls) != set(calls):
            return []
        references = self._factory_references(function, argument)
        if references is None:
            return []
        return [self._replace(node, repr(value.value)) for node in references]

    def _factory_references(self, function: ast.FunctionDef, argument: ast.arg) -> list[ast.Name] | None:
        nodes = [node for statement in function.body for node in ast.walk(statement)]
        if any(isinstance(node, _NESTED_SCOPES) for node in nodes):
            return None
        if any(
            isinstance(node, ast.AnnAssign)
            and any(isinstance(item, ast.Name) and item.id == argument.arg for item in ast.walk(node.annotation))
            for node in nodes
        ):
            return None
        references = [node for node in nodes if isinstance(node, ast.Name) and node.id == argument.arg]
        if any(not isinstance(node.ctx, ast.Load) for node in references):
            return None
        return references

    def _closed(self, function: ast.FunctionDef, *, allow_keyword_capture: bool = False) -> bool:
        if (
            function.args.vararg is not None
            or (function.args.kwarg is not None and not allow_keyword_capture)
            or not private_unescaped_function(function, self.context)
        ):
            return False
        owner: ast.AST | None = function
        while owner is not None:
            if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and owner.type_params:
                return False
            owner = self.context.parents.get(owner)
        return True

    def _calls(self, function: ast.FunctionDef) -> list[ast.Call] | None:
        calls: list[ast.Call] = []
        for reference in self.context.nodes(ast.Name):
            if reference.id != function.name:
                continue
            owner = self.context.parents.get(reference)
            while owner is not None:
                if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.TypeAlias)) and any(
                    not isinstance(parameter, (ast.TypeVar, ast.TypeVarTuple, ast.ParamSpec))
                    or parameter.name == function.name
                    for parameter in owner.type_params
                ):
                    return None
                owner = self.context.parents.get(owner)
            call = direct_call(reference, self.context)
            if (
                call is None
                or not call_matches(function, call)
                or self.provenance.binding(reference.id, reference) is not function
            ):
                return None
            calls.append(call)
        return calls

    def _signature(self, function: ast.FunctionDef, argument: ast.arg) -> list[TextEdit]:
        start = self._offset(function.lineno, function.col_offset)
        opened = False
        depth = 0
        parts: list[_Part] = []
        inside_start = segment_start = 0
        for token in self.tokens:
            token_start = self.starts[token.start[0] - 1] + token.start[1]
            token_end = self.starts[token.end[0] - 1] + token.end[1]
            if token_start < start or token.type != tokenize.OP:
                continue
            if not opened:
                if token.string != "(":
                    continue
                opened = True
                inside_start = segment_start = token_end
                depth = 1
            elif token.string in "([{":
                depth += 1
            elif token.string in ")]}":
                depth -= 1
                if depth == 0:
                    parts.append(_Part(segment_start, token_start))
                    return self._without_argument(
                        function,
                        argument,
                        parts,
                        start=inside_start,
                        end=token_start,
                        closing_line=token.end[0],
                    )
            elif token.string == "," and depth == 1:
                parts.append(_Part(segment_start, token_start))
                segment_start = token_end
        return []

    def _without_argument(
        self,
        function: ast.FunctionDef,
        argument: ast.arg,
        parts: list[_Part],
        *,
        start: int,
        end: int,
        closing_line: int,
    ) -> list[TextEdit]:
        if self._comments(function.lineno, closing_line):
            return []
        position = self._offset(argument.lineno, argument.col_offset)
        retained = [
            self.context.source[part.start : part.end]
            for part in parts
            if self._retain_signature_part(function, argument, part, position)
        ]
        replacement = ",".join(retained)
        if not replacement.strip():
            replacement = ""
        elif "\n" not in replacement:
            replacement = replacement.lstrip(" \t")
        return [TextEdit(start, end, replacement)]

    def _retain_signature_part(self, function: ast.FunctionDef, argument: ast.arg, part: _Part, position: int) -> bool:
        if part.start <= position < part.end:
            return False
        return not (
            len(function.args.kwonlyargs) == 1
            and argument in function.args.kwonlyargs
            and function.args.vararg is None
            and self.context.source[part.start : part.end].strip() == "*"
        )

    def _comments(self, first: int, last: int) -> bool:
        return any(token.type == tokenize.COMMENT and first <= token.start[0] <= last for token in self.tokens)

    def _offset(self, line: int, byte_column: int) -> int:
        return self.starts[line - 1] + len(self.lines[line - 1].encode("utf-8")[:byte_column].decode("utf-8"))

    def _replace(self, node: ast.expr, replacement: str) -> TextEdit:
        return TextEdit(
            self._offset(node.lineno, node.col_offset),
            self._offset(node.end_lineno or node.lineno, node.end_col_offset or node.col_offset),
            replacement,
        )
