from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

from sarj_python_lint.rules._ast_index import walk
from sarj_python_lint.rules._sql import sql_string_value
from sarj_python_lint.rules._sql_aggregate_identity import aggregate_name
from sarj_python_lint.rules._sql_policy_source import normalize_group_comments


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from sqlglot import exp

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._nominal_project import NominalSource


_DRIVERS = (
    ("postgres", ("asyncpg", "psycopg", "psycopg2", "psycopg_pool", "sqlalchemy.dialects.postgresql")),
    ("sqlite", ("sqlite3", "aiosqlite", "sqlalchemy.dialects.sqlite")),
    ("mysql", ("mysql.connector", "pymysql", "aiomysql", "asyncmy", "sqlalchemy.dialects.mysql")),
    (
        "analytical",
        (
            "clickhouse_connect",
            "clickhouse_driver",
            "asynch",
            "google.cloud.bigquery",
            "duckdb",
            "snowflake.connector",
            "trino",
            "pyathena",
            "databricks.sql",
        ),
    ),
)
_CONNECTION_METHODS = frozenset({"connection", "cursor", "acquire"})
_QUERY_METHODS = frozenset(
    {"execute", "executemany", "fetch", "fetchall", "fetchone", "fetchrow", "fetchval", "prepare", "query", "command"}
)
_QUERY_KEYWORDS = frozenset({"query", "sql", "statement", "command", "operation"})
_NATIVE_CONNECTIONS = frozenset(
    {
        "asyncpg.connect",
        "asyncpg.create_pool",
        "asyncpg.Connection",
        "asyncpg.Pool",
        "psycopg.connect",
        "psycopg.Connection",
        "psycopg.Connection.connect",
        "psycopg.AsyncConnection",
        "psycopg.AsyncConnection.connect",
        "psycopg.Cursor",
        "psycopg.AsyncCursor",
        "psycopg2.connect",
        "psycopg2.extensions.connection",
        "psycopg2.extensions.cursor",
        "psycopg_pool.ConnectionPool",
        "psycopg_pool.AsyncConnectionPool",
        "sqlite3.connect",
        "sqlite3.Connection",
        "sqlite3.Cursor",
        "aiosqlite.connect",
        "aiosqlite.Connection",
        "aiosqlite.Cursor",
        "pymysql.connect",
        "pymysql.Connection",
        "pymysql.connections.Connection",
        "mysql.connector.connect",
        "mysql.connector.MySQLConnection",
        "mysql.connector.connection.MySQLConnection",
        "mysql.connector.pooling.MySQLConnectionPool",
        "aiomysql.connect",
        "aiomysql.create_pool",
        "aiomysql.Connection",
        "aiomysql.Pool",
        "asyncmy.connect",
        "asyncmy.create_pool",
        "asyncmy.Connection",
        "asyncmy.Pool",
    }
)
_SELECT = re.compile(r"\bSELECT\b", re.IGNORECASE)
_PLACEHOLDER = re.compile(r"%(?:\([^)]+\))?s")
_FORMAT_HOLE = re.compile(r"(?<!\{)\{(?:[A-Za-z_]\w*|\d*)\}(?!\})")
_SQL_HOLE = "__sarj_sql_hole__"
_MAX_WRAPPER_DEPTH = 8


@dataclass(frozen=True, slots=True)
class TransactionalQuery:
    node: ast.expr
    sql: str
    dialect: str


@dataclass(frozen=True, slots=True)
class _RecoveredQuery:
    node: ast.expr
    sql: str


def query_signal(sql: str, *, dialect: str = "postgres") -> str | None:
    if _SELECT.search(sql) is None:
        return None
    import sqlglot  # ruff: ignore[import-outside-top-level] -- SQL parsing is unnecessary for unrelated Python.
    from sqlglot.errors import SqlglotError  # ruff: ignore[import-outside-top-level] -- paired with the lazy parser.

    try:
        prepared = _prepared_sql(sql, dialect)
        statements = [
            (statement, text)
            for text in _statement_texts(prepared, dialect)
            for statement in sqlglot.parse(text, read=dialect)
        ]
    except SqlglotError, RecursionError:
        return None
    for statement, text in statements:
        if statement is not None and (signal := _statement_signal(statement, text, dialect)) is not None:
            return signal
    return None


def _prepared_sql(sql: str, dialect: str) -> str:
    prepared = _FORMAT_HOLE.sub(_SQL_HOLE, _PLACEHOLDER.sub("?", sql))
    if dialect == "postgres" and "EXPLAIN" in prepared.upper():
        from sarj_python_lint.rules._sql_explain import normalize_postgres_explain  # ruff: ignore[import-outside-top-level] -- only executing EXPLAIN needs native token normalization.

        prepared = normalize_postgres_explain(prepared)
    if "GROUP" in prepared.upper() and ("/*" in prepared or "--" in prepared):
        import sqlglot  # ruff: ignore[import-outside-top-level] -- tokenize only GROUP candidates with comments.

        return normalize_group_comments(prepared, sqlglot.tokenize(prepared, read=dialect))
    return prepared


def _statement_texts(sql: str, dialect: str) -> Iterator[str]:
    if ";" not in sql:
        yield sql
        return
    import sqlglot  # ruff: ignore[import-outside-top-level] -- split only multi-statement candidates.
    from sqlglot.tokenizer_core import TokenType  # ruff: ignore[import-outside-top-level] -- quoted semicolons are data.

    start = 0
    for token in sqlglot.tokenize(sql, read=dialect):
        if token.token_type is TokenType.SEMICOLON:
            yield sql[start : token.start]
            start = token.end + 1
    yield sql[start:]


def _statement_signal(statement: exp.Expr, sql: str, dialect: str) -> str | None:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- paired with the lazy parser.

    if isinstance(statement, exp.Describe) and statement.args.get("style") != "ANALYZE":
        return None
    for node in statement.walk():
        if isinstance(node, exp.SetOperation) and node.args.get("distinct") is not False:
            return "deduplicating set operation"
        if isinstance(node, exp.Select):
            if node.args.get("distinct") is not None:
                return "DISTINCT"
            if node.args.get("group") is not None:
                return "GROUP BY"
        if node.find_ancestor(exp.Select) is not None and (name := aggregate_name(node, sql, dialect)) is not None:
            return f"{name} aggregate"
    return None


def transactional_queries(context: PythonFileContext) -> Iterator[TransactionalQuery]:
    if _SELECT.search(context.source) is None:
        return
    dialects = _source_dialects(context)
    if not dialects or dialects == {"analytical"}:
        return
    single = next(iter(dialects)) if len(dialects) == 1 else None
    for candidate in _recover_queries(context):
        dialect = single or _executing_dialect(candidate.node, context)
        if dialect is not None and dialect != "analytical":
            yield TransactionalQuery(candidate.node, candidate.sql, dialect)


def _recover_queries(context: PythonFileContext) -> Iterator[_RecoveredQuery]:
    consumed: set[int] = set()
    for node in context.nodes(ast.Constant, ast.BinOp, ast.JoinedStr):
        if id(node) in consumed or id(node) in context.docstring_node_ids:
            continue
        sql = _query_text(node)
        if sql is None:
            continue
        # Examine a recoverable composition once, including its static children.
        if isinstance(node, ast.BinOp | ast.JoinedStr):
            consumed.update(id(child) for child in walk(node))
        if _SELECT.search(sql) is None:
            continue
        yield _RecoveredQuery(node, sql)


def _driver_dialect(qualified: str) -> str | None:
    return next(
        (
            dialect
            for dialect, prefixes in _DRIVERS
            for prefix in prefixes
            if qualified == prefix or qualified.startswith(f"{prefix}.")
        ),
        None,
    )


def _source_dialects(context: PythonFileContext) -> set[str]:
    dialects: set[str] = set()
    for node in context.nodes(ast.Import, ast.ImportFrom):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            names = (f"{node.module}.{alias.name}" for alias in node.names)
        else:
            names = (alias.name for alias in node.names)
        dialects.update(dialect for name in names if (dialect := _driver_dialect(name)) is not None)
    if dialects and "analytical" not in dialects and _has_analytical_wrapper(context):
        dialects.add("analytical")
    return dialects


def _has_analytical_wrapper(context: PythonFileContext) -> bool:
    qualified: set[str] = set()
    for declaration in context.nodes(ast.arg, ast.AnnAssign):
        qualified.update(_annotation_references(declaration.annotation, context))
    if not qualified:
        return False
    # Distribution ownership also covers namespaces shared by workspace members.
    sources = context.session.nominal_project.sources(context.path, context.session.first_party, include_generated=True)
    return any(_analytical_query_type(name, sources, frozenset()) for name in qualified)


def _annotation_references(annotation: ast.expr | None, context: PythonFileContext) -> set[str]:
    if annotation is None:
        return set()
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError, ValueError, RecursionError:
            return set()
    qualified: set[str] = set()
    for node in walk(annotation):
        if (
            isinstance(node, ast.Name | ast.Attribute)
            and (name := _annotation_qualified_name(node, context)) is not None
        ):
            qualified.add(name)
    return qualified


def _annotation_qualified_name(node: ast.expr, context: PythonFileContext) -> str | None:
    root = node
    while isinstance(root, ast.Attribute):
        root = root.value
    if not isinstance(root, ast.Name) or context.has_wildcard_import:
        return None
    if root.id in context.imports.shadowed_names:
        return None
    return context.module_imports.resolved_qualified_name(node)


def _analytical_query_type(qualified: str, sources: Mapping[str, NominalSource], seen: frozenset[str]) -> bool:
    if qualified in seen or len(seen) >= _MAX_WRAPPER_DEPTH:
        return False
    module, _, symbol = qualified.rpartition(".")
    source = sources.get(module)
    if source is None or source.tree is None:
        return False
    seen |= {qualified}
    reference = ast.Name(id=symbol, ctx=ast.Load())
    exported = source.imports.resolved_qualified_name(reference)
    if exported is not None and exported != qualified:
        return _analytical_query_type(exported, sources, seen)
    declaration = next(
        (node for node in source.tree.body if isinstance(node, ast.ClassDef) and node.name == symbol), None
    )
    if declaration is None:
        return False
    if _declares_query(declaration) and _has_analytical_driver(source.tree):
        return True
    return any(
        _analytical_query_type(_base_qualified(base, module, source), sources, seen) for base in declaration.bases
    )


def _declares_query(node: ast.ClassDef) -> bool:
    return any(
        isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef) and member.name in _QUERY_METHODS
        for member in node.body
    )


def _has_analytical_driver(tree: ast.Module) -> bool:
    for node in walk(tree):
        if isinstance(node, ast.Import):
            names = (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names = (f"{node.module}.{alias.name}" for alias in node.names)
        else:
            continue
        if any(_driver_dialect(name) == "analytical" for name in names):
            return True
    return False


def _base_qualified(base: ast.expr, module: str, source: NominalSource) -> str:
    base = base.value if isinstance(base, ast.Subscript) else base
    imported = source.imports.resolved_qualified_name(base)
    if imported is not None:
        return imported
    return f"{module}.{base.id}" if isinstance(base, ast.Name) else ""


def _query_text(node: ast.expr) -> str | None:
    value = sql_string_value(node, interpolation_placeholder=_SQL_HOLE)
    if value is not None:
        return value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _query_text(node.left), _query_text(node.right)
        if left is not None or right is not None:
            return (left or _SQL_HOLE) + (right or _SQL_HOLE)
    return None


def _executing_dialect(node: ast.expr, context: PythonFileContext) -> str | None:
    current: ast.AST = node
    while (parent := context.parents.get(current)) is not None:
        if isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute):
            argument = _query_argument(parent)
            if argument is current or (isinstance(current, ast.keyword) and argument is current.value):
                return _receiver_dialect(parent.func.value, context, seen=frozenset())
        if isinstance(parent, ast.stmt):
            return None
        current = parent
    return None


def _query_argument(call: ast.Call) -> ast.expr | None:
    if not isinstance(call.func, ast.Attribute) or call.func.attr not in _QUERY_METHODS:
        return None
    if call.args:
        return call.args[0]
    return next((item.value for item in call.keywords if item.arg in _QUERY_KEYWORDS), None)


def _receiver_dialect(node: ast.expr, context: PythonFileContext, *, seen: frozenset[int]) -> str | None:
    if id(node) in seen:
        return None
    seen |= {id(node)}
    if isinstance(node, ast.Await):
        return _receiver_dialect(node.value, context, seen=seen)
    provenance = context.static_resource_provenance
    if isinstance(node, ast.Name):
        if not provenance.unescaped(node, node, allow_context=True):
            return None
        binding = provenance.runtime_binding(node.id, node)
        if isinstance(binding, ast.arg) and binding.annotation is not None:
            return _annotation_dialect(binding.annotation, context)
        if isinstance(binding, ast.Name) and (value := provenance.assignment_value(binding, node)) is not None:
            return _receiver_dialect(value, context, seen=seen)
        constructor = provenance.constructor(node, node)
        return _receiver_dialect(constructor, context, seen=seen) if constructor is not None else None
    if isinstance(node, ast.Call):
        qualified = provenance.runtime_import_name(node.func)
        if qualified in _NATIVE_CONNECTIONS:
            return _driver_dialect(qualified)
        if isinstance(node.func, ast.Attribute) and node.func.attr in _CONNECTION_METHODS:
            return _receiver_dialect(node.func.value, context, seen=seen)
    return None


def _annotation_dialect(node: ast.expr, context: PythonFileContext) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError, ValueError, RecursionError:
            return None
    annotation = node.value if isinstance(node, ast.Subscript) else node
    qualified = _annotation_qualified_name(annotation, context)
    return _driver_dialect(qualified) if qualified in _NATIVE_CONNECTIONS else None
