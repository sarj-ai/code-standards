from __future__ import annotations

import ast
from io import StringIO
import re
import tokenize
from typing import TYPE_CHECKING, final

from sarj_rule_contracts import TextEdit

from sarj_python_lint.rule_base import Severity
from sarj_python_lint.rules._comment_narration import CommentNarration, same_words
from sarj_python_lint.rules._prose_budget import groups
from sarj_python_lint.rules.trailing_value_narration import UNIT_WORDS, number_key


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


_NUMBER_AND_UNIT = re.compile(r"([0-9][0-9_]*(?:\.[0-9_]+)?)\s*([A-Za-z]+)\Z")
_UNUSED_API_DIRECTIVE = re.compile(
    r"#\s*ruff:\s*(?:noqa\s*:\s*TID251|file-ignore\s*\[\s*(?:TID251|banned-api)\s*\])\s*\Z",
    re.IGNORECASE,
)
_MIN_PARAGRAPH_LINES = 4


@final
class CommentFixes:
    def __init__(self, context: PythonFileContext) -> None:
        self.context = context
        self.lines = StringIO(context.source, newline="").readlines()
        self.starts = [0]
        for line in self.lines:
            self.starts.append(self.starts[-1] + len(line))
        self.comments = {
            token.start[0]: token
            for token in tokenize.generate_tokens(StringIO(context.source, newline="").readline)
            if token.type == tokenize.COMMENT
        }
        self.statements: dict[int, list[ast.stmt]] = {}
        for statement in context.nodes(ast.stmt):
            self.statements.setdefault(statement.lineno, []).append(statement)
        self.prose_groups = {(group.line, group.col): group for group in groups(context.path, context.source)}
        self.narration: CommentNarration | None = None

    def fixes(self, diagnostic: Diagnostic) -> list[TextEdit]:
        token = self.comments.get(diagnostic.line)
        if token is None or token.start[1] + 1 != diagnostic.col:
            return []
        if diagnostic.code == "SARJ049" and self._restates_call(token):
            return [self._remove(token)]
        if diagnostic.code == "SARJ051" and self._unit_already_agrees(token):
            return [self._remove(token)]
        if diagnostic.code == "SARJ054" and self._unused_api_directive(token):
            return [self._remove(token)]
        if diagnostic.code == "SARJ434" and diagnostic.severity is Severity.ERROR:
            paragraph = self._restates_accumulation(token)
            return [self._remove(comment) for comment in paragraph]
        return []

    def _unused_api_directive(self, comment: tokenize.TokenInfo) -> bool:
        tree = self.context.tree
        return (
            tree is not None
            and bool(tree.body)
            and len(self.comments) == 1
            and not self.lines[comment.start[0] - 1][: comment.start[1]].strip()
            and _UNUSED_API_DIRECTIVE.fullmatch(comment.string) is not None
            and all(_literal_name_assignment(statement) for statement in tree.body)
        )

    def _restates_call(self, comment: tokenize.TokenInfo) -> bool:
        if self.lines[comment.start[0] - 1][: comment.start[1]].strip():
            return False
        statement = self._only_statement(comment.end[0] + 1)
        match statement:
            case ast.Expr(value=ast.Call(func=ast.Name(id=name))):
                return (
                    statement.col_offset == comment.start[1]
                    and statement.lineno == statement.end_lineno
                    and same_words(comment.string.removeprefix("#").strip(), name)
                )
            case _:
                return False

    def _only_statement(self, line: int) -> ast.stmt | None:
        statements = self.statements.get(line, [])
        return statements[0] if len(statements) == 1 else None

    def _unit_already_agrees(self, comment: tokenize.TokenInfo) -> bool:
        statement = self._only_statement(comment.start[0])
        match statement:
            case (
                ast.Assign(targets=[ast.Name(id=name)], value=ast.Constant(value=value))
                | ast.AnnAssign(target=ast.Name(id=name), value=ast.Constant(value=value))
            ):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                    return False
                match = _NUMBER_AND_UNIT.fullmatch(comment.string.removeprefix("#").strip())
                if match is None:
                    return False
                number, unit = match.groups()
                value_key = number_key(value)
                return (
                    value_key is not None
                    and unit.casefold() in UNIT_WORDS
                    and "_" in name
                    and name.rsplit("_", 1)[-1].casefold() == unit.casefold()
                    and number_key(number) == value_key
                )
            case _:
                return False

    def _restates_accumulation(self, first: tokenize.TokenInfo) -> list[tokenize.TokenInfo]:
        group = self.prose_groups.get((first.start[0], first.start[1] + 1))
        if group is None:
            return []
        if self.narration is None:
            self.narration = CommentNarration(self.context)
        matched = self.narration.match(group)
        if (
            matched is not None
            and matched.kind == "accumulation"
            and len(matched.comment_lines) >= _MIN_PARAGRAPH_LINES
        ):
            return [self.comments[line] for line in matched.comment_lines]
        return []

    def _remove(self, comment: tokenize.TokenInfo) -> TextEdit:
        line = comment.start[0]
        prefix = self.lines[line - 1][: comment.start[1]]
        start_column = len(prefix.rstrip())
        return TextEdit(
            self.starts[line - 1] + start_column,
            self.starts[comment.end[0] - 1] + comment.end[1],
            "",
        )


def _literal_name_assignment(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, (str, bytes, int, float, complex, bool, type(None)))
    )
