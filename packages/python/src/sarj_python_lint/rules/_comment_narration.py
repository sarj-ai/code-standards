from __future__ import annotations

import ast
from bisect import bisect_left
import re
from typing import TYPE_CHECKING, Literal, NamedTuple, final

from sarj_python_lint.rules._comments import comment_line_numbers, has_narration_qualifier, is_protected


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._prose_budget import ProseGroup


_IDENTIFIER = re.compile(r"[a-z]+(?:_[a-z]+)+\Z")
_WORDS = re.compile(r"[A-Za-z]+(?:\s+[A-Za-z]+)*\.?\Z")
_ACCUMULATOR_METHODS = frozenset({"add", "append", "extend", "update"})
_MIN_LINES = 2
_MIN_WORDS = 12


class NarrationMatch(NamedTuple):
    kind: Literal["accumulation", "actions"]
    comment_lines: tuple[int, ...]


@final
class CommentNarration:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.comment_lines = tuple(sorted(comment_line_numbers(context.source)))
        self.statements: dict[int, list[ast.stmt]] = {}
        for statement in context.nodes(ast.stmt):
            self.statements.setdefault(statement.lineno, []).append(statement)

    def match(self, group: ProseGroup) -> NarrationMatch | None:
        lines = group.text.splitlines()
        if (
            group.kind != "comment"
            or len(lines) < _MIN_LINES
            or len(group.text.split()) < _MIN_WORDS
            or any(not line.strip() for line in lines)
            or any(has_narration_qualifier(line) or is_protected(line) for line in lines)
        ):
            return None
        following = self.statements.get(group.line + len(lines), [])
        if len(following) != 1:
            return None
        first = following[0]
        owner = self.context.parents.get(first)
        if (
            not isinstance(owner, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef))
            or owner.body[0] is not first
            or first.col_offset != group.col - 1
            or self._intervening_comment(first, owner.body[-1])
        ):
            return None
        if self._accumulation(owner, lines):
            return NarrationMatch("accumulation", tuple(range(group.line, group.line + len(lines))))
        if (
            len(owner.body) == len(lines)
            and not any(isinstance(node, ast.Return) for node in owner.body[:-1])
            and all(
                (called := _direct_action_call(statement)) is not None and same_words(line, called)
                for line, statement in zip(lines, owner.body, strict=True)
            )
        ):
            return NarrationMatch("actions", tuple(range(group.line, group.line + len(lines))))
        return None

    def _intervening_comment(self, first: ast.stmt, last: ast.stmt) -> bool:
        index = bisect_left(self.comment_lines, first.lineno)
        return index < len(self.comment_lines) and self.comment_lines[index] <= (last.end_lineno or last.lineno)

    def _accumulation(self, owner: ast.Module | ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]) -> bool:
        if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)) or len(owner.body) != len(lines) + 2:
            return False
        name = empty_collection_name(owner.body[0], self.context)
        returned = owner.body[-1]
        if (
            name is None
            or not isinstance(returned, ast.Return)
            or not isinstance(returned.value, ast.Name)
            or returned.value.id != name
        ):
            return False
        return all(
            (called := _accumulated_call(statement, name)) is not None and same_words(line, called)
            for line, statement in zip(lines, owner.body[1:-1], strict=True)
        )


def same_words(body: str, identifier: str) -> bool:
    identifier = identifier.strip("_")
    return (
        _IDENTIFIER.fullmatch(identifier) is not None
        and _WORDS.fullmatch(body) is not None
        and body.removesuffix(".").casefold().split() == identifier.split("_")
    )


def empty_collection_name(statement: ast.stmt, context: PythonFileContext) -> str | None:
    target: ast.expr | None = None
    value: ast.expr | None = None
    if isinstance(statement, ast.AnnAssign):
        target, value = statement.target, statement.value
    elif isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target, value = statement.targets[0], statement.value
    if not isinstance(target, ast.Name) or value is None:
        return None
    if isinstance(value, (ast.List, ast.Set)) and not value.elts:
        return target.id
    if isinstance(value, ast.Dict) and not value.keys:
        return target.id
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in {"dict", "list", "set"}
        and not value.args
        and not value.keywords
    ):
        provenance = context.static_resource_provenance
        if provenance.builtin_namespace_untouched and provenance.binding(value.func.id, value.func) is None:
            return target.id
    return None


def _direct_action_call(statement: ast.stmt) -> str | None:
    match statement:
        case ast.Expr(value=value) | ast.Assign(targets=[ast.Name()], value=value) | ast.Return(value=value):
            return _zero_argument_call(value)
        case _:
            return None


def _zero_argument_call(value: ast.AST | None) -> str | None:
    match value:
        case ast.Call(func=ast.Name(id=called), args=[], keywords=[]):
            return called
        case _:
            return None


def _accumulated_call(statement: ast.stmt, collection: str) -> str | None:
    match statement:
        case ast.Expr(
            value=ast.Call(
                func=ast.Attribute(value=ast.Name(id=name), attr=method),
                args=[value],
                keywords=[],
            )
        ):
            return _zero_argument_call(value) if name == collection and method in _ACCUMULATOR_METHODS else None
        case _:
            return None
