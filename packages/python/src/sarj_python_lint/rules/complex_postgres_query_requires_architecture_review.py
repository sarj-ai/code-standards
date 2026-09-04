from __future__ import annotations

import ast
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_python_lint.rule_base import (
    AutofixPolicy,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    Severity,
    parse_or_none,
)
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_generated
from sarj_python_lint.rules._sql import is_store_module, sql_string_value, strip_sql_noise


if TYPE_CHECKING:
    from pathlib import Path

    from sqlglot import exp


_QUERY_SHAPE = re.compile(r"\bSELECT\b[\s\S]*?\bFROM\b", re.IGNORECASE)
_DERIVED_RELATION_GATE = re.compile(r"\b(?:FROM|JOIN)\s*\(", re.IGNORECASE)
_POSTGRES_IMPORT_PREFIXES = (
    "asyncpg",
    "psycopg",
    "psycopg2",
    "psycopg_pool",
    "sqlalchemy.dialects.postgresql",
)
_COMPETING_IMPORT_PREFIXES = (
    "aiosqlite",
    "clickhouse_connect",
    "clickhouse_driver",
    "google.cloud.bigquery",
    "sqlite3",
)
_QUERY_SINKS = frozenset({"execute", "executemany", "fetch", "fetchrow", "fetchval", "prepare"})
_QUERY_KEYWORDS = frozenset({"command", "operation", "query", "statement"})
_QUERY_RECEIVER_TOKENS = frozenset(
    {"client", "con", "conn", "connection", "cur", "cursor", "database", "db", "pg", "pool", "session"}
)
_CLICKHOUSE_SQL = re.compile(
    r"\barg(?:Max|Min)\b|\b_peerdb|\bJSONExtract|\buniqExact\b|\bgroupArray\b"
    r"|\barrayJoin\b|\bquantile\w*\(",
)
_BIGQUERY_SQL = re.compile(
    r"\b(?:FROM|JOIN)\s+`|\bAPPROX_COUNT_DISTINCT\s*\(|\bGENERATE_ARRAY\s*\("
    r"|\b_PARTITIONTIME\b|\bSAFE_CAST\s*\(|\bPARSE_TIMESTAMP\s*\("
    r"|\bCOUNTIF\s*\(|\bSTRUCT\s*\(",
    re.IGNORECASE,
)
_COMPOSABLE_HOLE = re.compile(r"(?<!\{)\{(?:[A-Za-z_]\w*|\d*)\}(?!\})")
_SQL_HOLE = "__sarj_sql_hole__"


class _ConstructorImport(NamedTuple):
    scope_id: int
    name: str


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    result: set[int] = set()
    for owner in nodes(tree, ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef):
        body = owner.body
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            result.add(id(value))
    return result


def _import_names(tree: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    for node in nodes(tree, ast.Import, ast.ImportFrom):
        if isinstance(node, ast.Import):
            names.update(alias.name.lower() for alias in node.names)
            continue
        if node.level:
            continue
        module = (node.module or "").lower()
        if module:
            names.add(module)
        names.update(f"{module}.{alias.name.lower()}" if module else alias.name.lower() for alias in node.names)
    return frozenset(names)


def _has_import_prefix(imports: frozenset[str], prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(f"{prefix}.") for name in imports for prefix in prefixes)


def _is_query_context(node: ast.expr, parents: dict[int, ast.AST], roots: frozenset[int]) -> bool:
    current: ast.AST = node
    while True:
        if id(current) in roots:
            return True
        if (parent := parents.get(id(current))) is None:
            return False
        current = parent


def _query_roots(tree: ast.Module, parents: dict[int, ast.AST]) -> frozenset[int]:
    binding_counts: dict[tuple[int, str], int] = {}
    binding_values: dict[tuple[int, str], ast.expr] = {}
    wildcard_scopes: set[int] = set()

    def count(owner: ast.AST, name: str) -> None:
        key = (id(owner), name)
        binding_counts[key] = binding_counts.get(key, 0) + 1

    for name in nodes(tree, ast.Name):
        if isinstance(name.ctx, (ast.Store, ast.Del)):
            count(_scope(name, parents), name.id)
    for argument in nodes(tree, ast.arg):
        count(_scope(argument, parents), argument.arg)
    for imported in nodes(tree, ast.Import, ast.ImportFrom):
        owner = _scope(imported, parents)
        for alias in imported.names:
            if alias.name == "*":
                wildcard_scopes.add(id(owner))
                continue
            count(owner, alias.asname or alias.name.split(".")[0])
    for definition in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef):
        parent = parents.get(id(definition))
        if parent is not None:
            count(_scope(parent, parents), definition.name)
    for handler in nodes(tree, ast.ExceptHandler):
        if handler.name:
            count(_scope(handler, parents), handler.name)
    for pattern in nodes(tree, ast.MatchAs, ast.MatchStar, ast.MatchMapping):
        name = pattern.name if isinstance(pattern, (ast.MatchAs, ast.MatchStar)) else pattern.rest
        if name:
            count(_scope(pattern, parents), name)
    for declaration in nodes(tree, ast.Global, ast.Nonlocal):
        for name in declaration.names:
            count(_scope(declaration, parents), name)

    constructor_imports = _postgres_sql_constructors(tree, parents)
    for assignment in nodes(tree, ast.Assign, ast.AnnAssign):
        target: ast.expr | None = None
        if isinstance(assignment, ast.Assign) and len(assignment.targets) == 1:
            target = assignment.targets[0]
        elif isinstance(assignment, ast.AnnAssign):
            target = assignment.target
        if not isinstance(target, ast.Name) or assignment.value is None:
            continue
        owner = _scope(assignment, parents)
        if parents.get(id(assignment)) is owner:
            binding_values[id(owner), target.id] = assignment.value

    roots: set[int] = set()
    for call in nodes(tree, ast.Call):
        argument = _query_argument(call)
        if argument is None:
            continue
        owner = _scope(call, parents)
        constructors = _visible_constructors(owner, constructor_imports, parents, binding_counts, wildcard_scopes)
        if not isinstance(argument, ast.Name):
            if (root := _recoverable_query_root(argument, constructors)) is not None:
                roots.add(id(root))
            continue
        key = (id(owner), argument.id)
        value = binding_values.get(key)
        if (
            value is not None
            and key[0] not in wildcard_scopes
            and binding_counts.get(key) == 1
            and (value.lineno, value.col_offset) < (call.lineno, call.col_offset)
            and (root := _recoverable_query_root(value, constructors)) is not None
        ):
            roots.add(id(root))
    return frozenset(roots)


def _scope(node: ast.AST, parents: dict[int, ast.AST]) -> ast.AST:
    current = node
    while not isinstance(current, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
        parent = parents.get(id(current))
        if parent is None:
            return current
        current = parent
    return current


def _query_argument(call: ast.Call) -> ast.expr | None:
    if not isinstance(call.func, ast.Attribute) or call.func.attr.lower() not in _QUERY_SINKS:
        return None
    receiver_node = call.func.value.func if isinstance(call.func.value, ast.Call) else call.func.value
    receiver = _call_name(receiver_node).lower().lstrip("_")
    tokens = frozenset(part for part in receiver.split("_") if part)
    if (
        receiver not in _QUERY_RECEIVER_TOKENS
        and not tokens.intersection(_QUERY_RECEIVER_TOKENS)
        and not any(receiver.endswith(suffix) for suffix in ("conn", "cur", "cursor", "session"))
    ):
        return None
    if call.args:
        return call.args[0]
    return next((keyword.value for keyword in call.keywords if keyword.arg in _QUERY_KEYWORDS), None)


def _call_name(function: ast.expr) -> str:
    match function:
        case ast.Name(id=name) | ast.Attribute(attr=name):
            return name
        case _:
            return ""


def _postgres_sql_constructors(tree: ast.Module, parents: dict[int, ast.AST]) -> frozenset[_ConstructorImport]:
    constructors: set[_ConstructorImport] = set()
    for node in nodes(tree, ast.Import, ast.ImportFrom):
        owner_id = id(_scope(node, parents))
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "psycopg.sql":
                    constructors.add(
                        _ConstructorImport(owner_id, f"{alias.asname}.SQL" if alias.asname else "psycopg.sql.SQL")
                    )
            continue
        if node.level:
            continue
        if node.module == "psycopg.sql":
            constructors.update(
                _ConstructorImport(owner_id, alias.asname or alias.name) for alias in node.names if alias.name == "SQL"
            )
        elif node.module == "psycopg":
            constructors.update(
                _ConstructorImport(owner_id, f"{alias.asname or alias.name}.SQL")
                for alias in node.names
                if alias.name == "sql"
            )
    return frozenset(constructors)


def _recoverable_query_root(node: ast.expr, constructors: frozenset[str]) -> ast.expr | None:
    if sql_string_value(node, interpolation_placeholder=_SQL_HOLE) is not None:
        return node
    if not isinstance(node, ast.Call):
        return None
    constructor_call = node
    if isinstance(node.func, ast.Attribute) and node.func.attr == "format" and isinstance(node.func.value, ast.Call):
        constructor_call = node.func.value
    if _qualified_name(constructor_call.func) not in constructors or not constructor_call.args:
        return None
    value = constructor_call.args[0]
    return value if sql_string_value(value, interpolation_placeholder=_SQL_HOLE) is not None else None


def _qualified_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        owner = _qualified_name(node.value)
        return f"{owner}.{node.attr}" if owner else node.attr
    return ""


def _visible_constructors(
    owner: ast.AST,
    imports: frozenset[_ConstructorImport],
    parents: dict[int, ast.AST],
    binding_counts: dict[tuple[int, str], int],
    wildcard_scopes: set[int],
) -> frozenset[str]:
    scope_chain: list[int] = []
    current = owner
    while True:
        scope_chain.append(id(current))
        parent = parents.get(id(current))
        if parent is None:
            break
        current = _scope(parent, parents)

    visible: set[str] = set()
    for constructor_import in imports:
        import_scope, constructor = constructor_import
        if import_scope not in scope_chain:
            continue
        import_index = scope_chain.index(import_scope)
        root = constructor.split(".")[0]
        if import_scope in wildcard_scopes or binding_counts.get((import_scope, root)) != 1:
            continue
        if any(
            scope_id in wildcard_scopes or binding_counts.get((scope_id, root), 0) > 0
            for scope_id in scope_chain[:import_index]
        ):
            continue
        visible.add(constructor)
    return frozenset(visible)


def _expression_arg(node: exp.Expr, key: str) -> exp.Expr | None:
    return next((child for child in node.iter_expressions() if child.arg_key == key), None)


def _expression_args(node: exp.Expr, key: str) -> tuple[exp.Expr, ...]:
    return tuple(child for child in node.iter_expressions() if child.arg_key == key)


def _parse_signal(sql: str) -> str | None:
    import sqlglot  # ruff: ignore[import-outside-top-level] -- parse only SQL that passes cheap ownership and shape gates
    from sqlglot.errors import SqlglotError  # ruff: ignore[import-outside-top-level] -- paired with lazy parser import

    normalized = _COMPOSABLE_HOLE.sub(_SQL_HOLE, sql)
    try:
        statements = sqlglot.parse(normalized, read="postgres")
    except SqlglotError:
        return None
    for statement in statements:
        if statement is not None and (signal := _architecture_signal(statement)) is not None:
            return signal
    return None


def _architecture_signal(statement: exp.Expr) -> str | None:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- keep parser startup off unrelated lint runs

    if not isinstance(statement, exp.Query):
        return None
    for select in _root_selects(statement):
        for join in _expression_args(select, "joins"):
            if not isinstance(join, exp.Join):
                continue
            if (derived := _derived_query(_expression_arg(join, "this"))) is not None and _has_complex_body(derived):
                return "Complex JOIN-derived query"
        from_clause = _expression_arg(select, "from_")
        if not isinstance(from_clause, exp.From):
            continue
        if (derived := _derived_query(_expression_arg(from_clause, "this"))) is not None and _has_complex_body(derived):
            return "Complex FROM-derived query"
    return None


def _root_selects(query: exp.Query) -> tuple[exp.Select, ...]:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- keep parser startup off unrelated lint runs

    if isinstance(query, exp.Select):
        return (query,)
    if not isinstance(query, exp.SetOperation):
        return ()
    branches: list[exp.Select] = []
    for key in ("this", "expression"):
        if isinstance((branch := _expression_arg(query, key)), exp.Query):
            branches.extend(_root_selects(branch))
    return tuple(branches)


def _has_complex_body(query: exp.Query) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- keep parser startup off unrelated lint runs

    if isinstance(query, exp.SetOperation):
        return True
    if not isinstance(query, exp.Select):
        return False
    if _expression_arg(query, "group") is not None or _expression_arg(query, "having") is not None:
        return True
    if any(window.parent_select is query for window in query.find_all(exp.Window)):
        return True
    from_clause = _expression_arg(query, "from_")
    if isinstance(from_clause, exp.From) and _derived_query(_expression_arg(from_clause, "this")) is not None:
        return True
    for join in _expression_args(query, "joins"):
        if isinstance(join, exp.Join) and _derived_query(_expression_arg(join, "this")) is not None:
            return True
    return False


def _derived_query(node: exp.Expr | None) -> exp.Query | None:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- keep parser startup off unrelated lint runs

    if isinstance(node, exp.Subquery) and isinstance((query := _expression_arg(node, "this")), exp.Query):
        return query
    return None


@final
class ComplexPostgresQueryRequiresArchitectureReview(Rule):
    id: str = "complex-postgres-query-requires-architecture-review"
    code: str = "SARJ437"
    documentation = RuleDocumentation(
        summary="Complex anonymous PostgreSQL relation stages merit readability review.",
        rationale=(
            "Anonymous derived relations with nested or transformational bodies can obscure query stages and make "
            "bounds, ordering, and locking semantics harder to review. Syntax alone does not establish runtime cost "
            "or justify materialization or offload."
        ),
        remediation=(
            "First verify bounds, ordering, and lock semantics. Use a semantics-preserving CTE when naming improves "
            "reviewability; it is not a performance optimization. Consider a view only for a reusable stable "
            "interface, a materialized view only for measured repeated reads with an explicit freshness contract, "
            "and a columnar store only for measured analytical workloads with an explicit synchronization contract."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only statically recoverable SQL passed to execute, executemany, fetch, fetchrow, fetchval, or prepare in recognized PostgreSQL store modules is analyzed.",
            "Execution receivers must use a conventional database name; custom wrappers and dynamically obtained receivers abstain.",
            "One direct, unambiguous simple-name binding in the same lexical scope is followed; standalone constants, branches, aliases, attributes, containers, wildcard imports, and cross-scope flow abstain.",
            "A derived relation is reported only when it contains nesting, a window, grouping, HAVING, or a set operation.",
            "Scalar, EXISTS, IN, and LATERAL subqueries are excluded; execution plans and production cardinality remain authoritative.",
            "A CTE is suggested only as a naming refactor; the rule does not infer optimizer behavior, materialization, performance, or datastore placement.",
        ),
        examples=(
            RuleExample(
                example_id="ranked-queue-claim",
                title="A queue claim hides ranking inside nested derived relations",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/call_store.py",
                        "import psycopg\n\n"
                        'cursor.execute("SELECT due.id FROM call AS due JOIN '
                        "(SELECT * FROM (SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rank FROM call) ranked "
                        'WHERE rank <= %s) picked ON picked.id = due.id FOR UPDATE OF due SKIP LOCKED")\n',
                    ),
                ),
                focus_path=PurePosixPath("app/call_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="named-queue-stages",
                title="A queue claim exposes ranking as named stages",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/call_store.py",
                        "import psycopg\n\n"
                        'cursor.execute("WITH ranked AS (SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rank FROM call), '
                        "picked AS (SELECT id FROM ranked WHERE rank <= %s) "
                        "SELECT due.id FROM call AS due JOIN picked ON picked.id = due.id "
                        'FOR UPDATE OF due SKIP LOCKED")\n',
                    ),
                ),
                focus_path=PurePosixPath("app/call_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if not is_store_module(path) or is_generated(path, source):
            return []
        tree = parse_or_none(path, source)
        if tree is None:
            return []
        imports = _import_names(tree)
        if not _has_import_prefix(imports, _POSTGRES_IMPORT_PREFIXES) or _has_import_prefix(
            imports, _COMPETING_IMPORT_PREFIXES
        ):
            return []

        docstrings = _docstring_node_ids(tree)
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        query_roots = _query_roots(tree, parents)
        diagnostics: list[Diagnostic] = []
        consumed: set[int] = set()
        for node in nodes(tree, ast.Constant, ast.BinOp, ast.JoinedStr):
            if id(node) in consumed or id(node) in docstrings or not _is_query_context(node, parents, query_roots):
                continue
            text_value = sql_string_value(node, interpolation_placeholder=_SQL_HOLE)
            if text_value is None:
                continue
            if isinstance(node, (ast.BinOp, ast.JoinedStr)):
                consumed.update(id(child) for child in walk(node))

            sql_without_noise = strip_sql_noise(text_value)
            if (
                _QUERY_SHAPE.search(sql_without_noise) is None
                or _DERIVED_RELATION_GATE.search(sql_without_noise) is None
                or _CLICKHOUSE_SQL.search(sql_without_noise)
                or _BIGQUERY_SQL.search(sql_without_noise)
            ):
                continue
            if (signal := _parse_signal(text_value)) is None:
                continue
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"{signal} hides a relational stage — review bounds, ordering, and locks; name it with a "
                        "semantics-preserving CTE if clearer. Reviewability warning only; no cost or offload claim."
                    ),
                )
            )
        diagnostics.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diagnostics
