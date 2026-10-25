from __future__ import annotations

import ast
from functools import cached_property
from typing import TYPE_CHECKING

from sarj_python_lint._fixes import python_source_hash
from sarj_python_lint._source import python_source_encoding
from sarj_python_lint.rule_base import AutofixPolicy, Fix, TextEdit
from sarj_python_lint.rules._suppression_comments import comment_lines


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_python_lint._file_context import PythonFileContext


_ALIAS_RETURN_LENGTH = 2
_NAMESPACE_MUTATORS = frozenset(
    {
        "setattr",
        "delattr",
        "setitem",
        "delitem",
        "__setattr__",
        "__delattr__",
        "__setitem__",
        "__delitem__",
        "__init__",
        "__ior__",
        "ior",
        "methodcaller",
        "patch",
        "clear",
        "pop",
        "popitem",
        "setdefault",
        "update",
    }
)


class LocalAliasFixes:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context

    @cached_property
    def _lines(self) -> tuple[bytes, ...]:
        return tuple(line.encode("utf-8") for line in self.context.source_lines)

    def spelling(self, node: ast.Name) -> str:
        return self._lines[node.lineno - 1][node.col_offset : node.end_col_offset].decode("utf-8")

    @cached_property
    def _available(self) -> bool:
        context = self.context
        return (
            python_source_encoding(context.source.encode("utf-8")) in {"utf-8", "utf-8-sig"}
            and context.imports.builtin_is_unshadowed("dict")
            and not any("dict" in bindings for bindings in context.resource_provenance.bindings.values())
            and context.resource_provenance.builtin_namespace_untouched
            and not any(node.attr == "__code__" for node in context.nodes(ast.Attribute))
            and not _visible_namespace_mutation(context)
        )

    @cached_property
    def _comments(self) -> Mapping[int, str]:
        return comment_lines(tuple(self.context.source_lines))

    @cached_property
    def _digest(self) -> str:
        return python_source_hash(self.context.source)

    def for_alias(self, assignment: ast.Assign, use: ast.Name) -> tuple[Fix, ...]:
        context = self.context
        owner = context.parents.get(assignment)
        if not isinstance(owner, ast.FunctionDef | ast.AsyncFunctionDef):
            return ()
        if not isinstance(context.parents.get(owner), ast.Module) or owner.decorator_list or owner.type_params:
            return ()
        args = owner.args
        parameters = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        if len(parameters) != 1 or args.vararg or args.kwarg or args.defaults or any(args.kw_defaults):
            return ()
        source = assignment.value
        if not isinstance(source, ast.Name) or parameters[0].arg != source.id:
            return ()
        body = owner.body[1:] if ast.get_docstring(owner) is not None else owner.body
        if len(body) != _ALIAS_RETURN_LENGTH or body[0] is not assignment or not isinstance(body[1], ast.Return):
            return ()
        call = body[1].value
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != "dict":
            return ()
        if call.args or len(call.keywords) != 1 or call.keywords[0].value is not use or not self._available:
            return ()
        edits = self._edits(assignment, use, source=source, owner=owner)
        if not edits:
            return ()
        return (Fix("Pass the original local directly", AutofixPolicy.SAFE, self._digest, edits),)

    def _edits(
        self,
        assignment: ast.Assign,
        use: ast.Name,
        *,
        source: ast.Name,
        owner: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> tuple[TextEdit, ...]:
        if any(line in self._comments for line in range(owner.lineno, (owner.end_lineno or owner.lineno) + 1)):
            return ()
        if assignment.end_lineno != assignment.lineno:
            return ()
        raw = self._lines[assignment.lineno - 1]
        if raw[: assignment.col_offset].strip() or raw[assignment.end_col_offset :].strip():
            return ()
        return (
            TextEdit(assignment.lineno, 1, assignment.lineno + 1, 1, ""),
            TextEdit(
                use.lineno,
                use.col_offset + 1,
                use.end_lineno or use.lineno,
                (use.end_col_offset or 0) + 1,
                self.spelling(source),
            ),
        )


def _visible_namespace_mutation(context: PythonFileContext) -> bool:
    if _imports_unittest(context):
        return True
    for node in context.nodes(ast.Name, ast.alias, ast.Attribute, ast.Subscript, ast.AugAssign):
        match node:
            case ast.Name(id=name) | ast.alias(name=name):
                if name in _NAMESPACE_MUTATORS:
                    return True
            case ast.Attribute(attr=name, ctx=ctx):
                if name in _NAMESPACE_MUTATORS or not isinstance(ctx, ast.Load):
                    return True
            case ast.Subscript(ctx=ctx):
                if not isinstance(ctx, ast.Load):
                    return True
            case ast.AugAssign(op=op):
                if isinstance(op, ast.BitOr):
                    return True
    return False


def _imports_unittest(context: PythonFileContext) -> bool:
    for node in context.nodes(ast.Import):
        if any(alias.name.partition(".")[0] == "unittest" for alias in node.names):
            return True
    return any(
        node.module is not None and node.module.partition(".")[0] == "unittest"
        for node in context.nodes(ast.ImportFrom)
    )
