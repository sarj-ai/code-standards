from __future__ import annotations

import ast
from io import StringIO
import re
import tokenize


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_OWNED_MODULE_STATEMENTS = 2


def has_comments(source: str) -> bool:
    return any(
        part.type == tokenize.COMMENT for part in tokenize.generate_tokens(StringIO(source, newline="").readline)
    )


def owned_literal(tree: ast.Module) -> ast.Constant | None:
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


def literal_query(source: str, literal: ast.Constant) -> str | None:
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
