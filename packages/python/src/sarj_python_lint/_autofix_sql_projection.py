from __future__ import annotations

import ast
from dataclasses import dataclass
from io import StringIO
import re
import tokenize
from typing import TYPE_CHECKING

from sarj_rule_contracts import TextEdit
from sqlglot import exp, parse_one
from sqlglot.errors import ParseError, TokenError

from sarj_python_lint.rules._ast_index import object_list


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rule_base import Diagnostic


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_QUERY = re.compile(
    r"[ \t]*SELECT[ \t]+(?P<star>\*)[ \t]+FROM[ \t]+"
    r"\([ \t]*VALUES[ \t]+\([ \t]*(?P<values>[0-9]{1,9}(?:[ \t]*,[ \t]*[0-9]{1,9}){0,7})"
    r'[ \t]*\)[ \t]*\)[ \t]+AS[ \t]+(?P<alias>"[A-Za-z_][A-Za-z0-9_]{0,62}")[ \t]*'
    r'\([ \t]*(?P<labels>"[A-Za-z_][A-Za-z0-9_]{0,62}"'
    r'(?:[ \t]*,[ \t]*"[A-Za-z_][A-Za-z0-9_]{0,62}"){0,7})[ \t]*\)'
    r"[ \t]*;?[ \t]*\Z",
    re.IGNORECASE | re.ASCII,
)
_QUERY_LIMIT = 2048
_OWNED_MODULE_STATEMENTS = 2


@dataclass(frozen=True, slots=True)
class _Projection:
    offset: int
    replacement: str


def fixes(context: PythonFileContext, diagnostic: Diagnostic) -> list[TextEdit]:
    tree = context.tree
    if tree is None or context.generated or _has_comments(context.source):
        return []
    literal = _owned_literal(tree)
    if literal is None or (literal.lineno, literal.col_offset + 1) != (diagnostic.line, diagnostic.col):
        return []
    query = _literal_query(context.source, literal)
    projection = _projection(query) if query is not None else None
    if projection is None:
        return []
    lines = StringIO(context.source, newline="").readlines()
    prefix = lines[literal.lineno - 1].encode("utf-8")[: literal.col_offset].decode("utf-8")
    start = sum(map(len, lines[: literal.lineno - 1])) + len(prefix) + 1 + projection.offset
    return [TextEdit(start, start + 1, projection.replacement)]


def _has_comments(source: str) -> bool:
    return any(
        part.type == tokenize.COMMENT for part in tokenize.generate_tokens(StringIO(source, newline="").readline)
    )


def _owned_literal(tree: ast.Module) -> ast.Constant | None:
    if len(tree.body) != _OWNED_MODULE_STATEMENTS:
        return None
    imported, owner = tree.body
    if not _canonical_import(imported) or not isinstance(owner, ast.FunctionDef) or not _plain_owner(owner):
        return None
    if owner.name == "Connection" or len(owner.body) != 1 or not isinstance(owner.body[0], ast.With):
        return None
    statement = owner.body[0]
    if len(statement.items) != 1 or len(statement.body) != 1 or statement.type_comment is not None:
        return None
    item = statement.items[0]
    if not _noarg_method(item.context_expr, "Connection", "connect") or not isinstance(item.optional_vars, ast.Name):
        return None
    receiver = item.optional_vars.id
    if _NAME.fullmatch(receiver) is None or receiver in {"Connection", owner.name}:
        return None
    return _returned_literal(statement.body[0], receiver)


def _canonical_import(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.ImportFrom)
        and node.level == 0
        and node.module == "psycopg"
        and len(node.names) == 1
        and node.names[0].name == "Connection"
        and node.names[0].asname is None
    )


def _plain_owner(owner: ast.FunctionDef) -> bool:
    arguments = owner.args
    return (
        _NAME.fullmatch(owner.name) is not None
        and not owner.decorator_list
        and not owner.type_params
        and owner.returns is None
        and owner.type_comment is None
        and not arguments.posonlyargs
        and not arguments.args
        and not arguments.kwonlyargs
        and arguments.vararg is None
        and arguments.kwarg is None
        and not arguments.defaults
        and not arguments.kw_defaults
    )


def _noarg_method(node: ast.expr, receiver: str, method: str) -> bool:
    return (
        isinstance(node, ast.Call)
        and not node.args
        and not node.keywords
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == method
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == receiver
    )


def _returned_literal(statement: ast.stmt, receiver: str) -> ast.Constant | None:
    if not isinstance(statement, ast.Return) or not isinstance(statement.value, ast.Call):
        return None
    fetched = statement.value
    if (
        fetched.args
        or fetched.keywords
        or not isinstance(fetched.func, ast.Attribute)
        or fetched.func.attr != "fetchall"
    ):
        return None
    executed = fetched.func.value
    if not isinstance(executed, ast.Call) or len(executed.args) != 1 or executed.keywords:
        return None
    if (
        not isinstance(executed.func, ast.Attribute)
        or executed.func.attr != "execute"
        or not isinstance(executed.func.value, ast.Name)
        or executed.func.value.id != receiver
    ):
        return None
    literal = executed.args[0]
    return literal if isinstance(literal, ast.Constant) and isinstance(literal.value, str) else None


def _literal_query(source: str, literal: ast.Constant) -> str | None:
    raw = ast.get_source_segment(source, literal)
    if (
        raw is None
        or literal.lineno != literal.end_lineno
        or not raw.startswith("'")
        or not raw.endswith("'")
        or not isinstance(literal.value, str)
    ):
        return None
    if "'" in raw[1:-1] or "\\" in raw or not raw.isascii() or raw[1:-1] != literal.value:
        return None
    parts = [
        part for part in tokenize.generate_tokens(StringIO(raw, newline="").readline) if part.type == tokenize.STRING
    ]
    return literal.value if len(parts) == 1 and parts[0].string == raw else None


def _projection(query: str) -> _Projection | None:
    if len(query) > _QUERY_LIMIT or (matched := _QUERY.fullmatch(query)) is None:
        return None
    labels = [part.strip() for part in matched["labels"].split(",")]
    if len(labels) != len(matched["values"].split(",")) or len(set(labels)) != len(labels):
        return None
    replacement = ", ".join(f"{matched['alias']}.{label}" for label in labels)
    candidate = query[: matched.start("star")] + replacement + query[matched.end("star") :]
    if not _projection_delta(query, candidate):
        return None
    return _Projection(offset=matched.start("star"), replacement=replacement)


def _projection_delta(original: str, candidate: str) -> bool:
    try:
        before = parse_one(original, read="postgres")
        after = parse_one(candidate, read="postgres")
    except ParseError, TokenError:
        return False
    if not isinstance(before, exp.Select) or not isinstance(after, exp.Select) or before.expressions != [exp.Star()]:
        return False
    columns = _projection_columns(after.expressions)
    if columns is None:
        return False
    expected = before.copy()
    expected.set("expressions", [part.copy() for part in columns])
    return expected == after


def _projection_columns(value: object) -> list[exp.Column] | None:
    if not object_list(value):
        return None
    columns: list[exp.Column] = []
    for part in value:
        if not isinstance(part, exp.Column):
            return None
        columns.append(part)
    return columns
