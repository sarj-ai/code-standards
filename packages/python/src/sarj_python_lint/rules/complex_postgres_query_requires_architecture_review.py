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
)
from sarj_python_lint.rules._ast_index import nodes, walk
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._sql import is_store_module, sql_string_value, strip_sql_noise
from sarj_python_lint.rules.no_analytical_aggregation_in_postgres_store import analytical_signal


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from sqlglot import exp

    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._ast_index import NodeIndex


_QUERY_SHAPE = re.compile(r"\bSELECT\b[\s\S]*?\bFROM\b", re.IGNORECASE)
_POSTGRES_IMPORT_PREFIXES = (
    "asyncpg",
    "psycopg",
    "psycopg2",
    "psycopg_pool",
    "sqlalchemy.dialects.postgresql",
)
_AMBIGUOUS_RELATIONAL_IMPORT_PREFIXES = ("aiosqlite", "sqlite3")
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
_JOIN_LIMIT = 4
_STAGE_LIMIT = 6
_COMBINED_JOIN_LIMIT = 3
_COMBINED_STAGE_LIMIT = 4
_WIDE_PROJECTION_LIMIT = 25
_WIDE_PROJECTION_JOIN_LIMIT = 2


class _ConstructorImport(NamedTuple):
    scope_id: int
    name: str


def _docstring_node_ids(tree: ast.AST, *, node_index: NodeIndex | None = None) -> set[int]:
    result: set[int] = set()
    for owner in nodes(tree, ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, index=node_index):
        body = owner.body
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            result.add(id(value))
    return result


def _is_query_context(node: ast.expr, parents: Mapping[ast.AST, ast.AST], roots: frozenset[int]) -> bool:
    current: ast.AST = node
    while True:
        if id(current) in roots:
            return True
        if (parent := parents.get(current)) is None:
            return False
        current = parent


def _query_roots(
    tree: ast.Module, parents: Mapping[ast.AST, ast.AST], *, node_index: NodeIndex | None = None
) -> frozenset[int]:
    binding_counts: dict[tuple[int, str], int] = {}
    binding_values: dict[tuple[int, str], ast.expr] = {}
    wildcard_scopes: set[int] = set()

    def count(owner: ast.AST, name: str) -> None:
        key = (id(owner), name)
        binding_counts[key] = binding_counts.get(key, 0) + 1

    _count_query_bindings(tree, parents, count, wildcard_scopes, node_index=node_index)

    constructor_imports = _postgres_sql_constructors(tree, parents, node_index=node_index)
    _query_binding_values(tree, parents, binding_values, node_index=node_index)

    roots: set[int] = set()
    for call in nodes(tree, ast.Call, index=node_index):
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


def _scope(node: ast.AST, parents: Mapping[ast.AST, ast.AST]) -> ast.AST:
    current = node
    while not isinstance(current, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
        parent = parents.get(current)
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
        and tokens.isdisjoint(_QUERY_RECEIVER_TOKENS)
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


def _postgres_sql_constructors(
    tree: ast.Module, parents: Mapping[ast.AST, ast.AST], *, node_index: NodeIndex | None = None
) -> frozenset[_ConstructorImport]:
    constructors: set[_ConstructorImport] = set()
    for node in nodes(tree, ast.Import, ast.ImportFrom, index=node_index):
        owner_id = id(_scope(node, parents))
        _record_sql_constructors(node, owner_id, constructors)
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
    parents: Mapping[ast.AST, ast.AST],
    binding_counts: dict[tuple[int, str], int],
    wildcard_scopes: set[int],
) -> frozenset[str]:
    scope_chain: list[int] = []
    current = owner
    while True:
        scope_chain.append(id(current))
        parent = parents.get(current)
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


def _derived_query(node: exp.Expr | None) -> exp.Query | None:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- keep parser startup off unrelated lint runs

    while isinstance(node, (exp.Lateral, exp.Paren, exp.Subquery)):
        node = _expression_arg(node, "this")
    return node if isinstance(node, exp.Query) else None


@final
class ComplexPostgresQueryRequiresArchitectureReview(Rule):
    id: str = "complex-postgres-query-requires-architecture-review"
    code: str = "SARJ437"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Complex executable PostgreSQL query shapes require architecture review.",
        rationale=(
            "Join-heavy, deeply staged, or wide joined reads can obscure cardinality, bounds, ordering, and locking "
            "semantics and can signal repeated read-time reconstruction. Syntax alone does not establish runtime "
            "cost, a bad data model, or the right datastore."
        ),
        remediation=(
            "Prefer ClickHouse for reporting, historical analysis, and broad aggregations, with measured performance "
            "and an explicit freshness contract. For transactional work, simplify the query or document why "
            "PostgreSQL is required, with query bounds and production-like EXPLAIN evidence. Review whether the "
            "schema exposes the operational fact directly; preserve atomic coordination and do not mechanically "
            "replace database joins with application joins. Do not add reporting-specific indexes without "
            "evaluating ClickHouse."
        ),
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only statically recoverable SQL passed to execute, executemany, fetch, fetchrow, fetchval, or prepare in non-test modules with explicit PostgreSQL imports is analyzed, regardless of module filename.",
            "Execution receivers must use a conventional database name; custom wrappers and dynamically obtained receivers abstain.",
            "One direct, unambiguous simple-name binding in the same lexical scope is followed; standalone constants, branches, aliases, attributes, containers, wildcard imports, and cross-scope flow abstain.",
            "Review covers derived relations in every SELECT (including LATERAL, CTEs, predicates and writes), four explicit or comma joins, six query stages, three joins plus four stages, or 25 projections plus two joins.",
            "Derived-relation review requires grouping, HAVING or windowing combined with joins or nested reads; expression density is not a separate trigger.",
            "Projection width alone is accepted, and UNION branches are measured independently; execution plans and production cardinality remain authoritative.",
            "ClickHouse and BigQuery syntax is excluded per query, including in mixed-backend modules.",
            "The rule does not infer optimizer behavior, materialization, performance, data-model quality, or datastore placement.",
        ),
        examples=(
            RuleExample(
                example_id="multi-join-root-discovery",
                title="A read repeatedly discovers a derived root through multiple joins",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.python(
                        "app/call_store.py",
                        'import psycopg\ncursor.execute("SELECT call.id FROM simulated_batch '
                        "JOIN batch_call ON batch_call.batch_id = simulated_batch.batch_id "
                        "JOIN call ON call.batch_call_id = batch_call.id "
                        "JOIN campaign_call ON campaign_call.call_id = call.id "
                        'JOIN campaign ON campaign.id = campaign_call.campaign_id WHERE simulated_batch.batch_id = %s")\n',
                    ),
                ),
                focus_path=PurePosixPath("app/call_store.py"),
                expected_count=1,
                public=True,
                scenario="multi-join-review",
            ),
            RuleExample(
                example_id="stored-root-lookup",
                title="A read uses a root resolved and stored by its owning write workflow",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/call_store.py",
                        'import psycopg\ncursor.execute("SELECT root_call_id FROM canary_run WHERE id = %s")\n',
                    ),
                ),
                focus_path=PurePosixPath("app/call_store.py"),
                expected_count=0,
                public=True,
                scenario="multi-join-review",
            ),
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
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        path = context.path
        if is_test_path(path) or context.generated:
            return []
        tree = context.tree
        if tree is None:
            return []
        if not _is_postgres_module(tree, node_index=context.node_index):
            return []

        docstrings = _docstring_node_ids(tree, node_index=context.node_index)
        parents = context.parents
        query_roots = _query_roots(tree, parents, node_index=context.node_index)
        diagnostics: list[Diagnostic] = []
        consumed: set[int] = set()
        for node in context.nodes(ast.Constant, ast.BinOp, ast.JoinedStr):
            if id(node) in consumed or id(node) in docstrings or not _is_query_context(node, parents, query_roots):
                continue
            text_value = sql_string_value(node, interpolation_placeholder=_SQL_HOLE)
            if text_value is None:
                continue
            if isinstance(node, (ast.BinOp, ast.JoinedStr)):
                consumed.update(id(child) for child in walk(node))

            signal = _query_architecture_signal(text_value, path)
            if signal is None:
                continue
            guidance = _query_review_guidance(text_value)
            diagnostics.append(
                Diagnostic(
                    path=path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    code=self.code,
                    severity=Severity.WARNING,
                    message=(
                        f"Complex PostgreSQL query: {signal}. Architecture review required;{guidance} "
                        "Prefer ClickHouse for reporting, historical analysis, and broad aggregations. "
                        "For transactional work, simplify the query or document why PostgreSQL is required, "
                        "with query bounds and EXPLAIN evidence. Do not add reporting-specific indexes without "
                        "evaluating ClickHouse. Syntax alone does not establish runtime cost or datastore placement."
                    ),
                )
            )
        diagnostics.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return diagnostics


def _count_query_bindings(
    tree: ast.Module,
    parents: Mapping[ast.AST, ast.AST],
    count: Callable[[ast.AST, str], None],
    wildcard_scopes: set[int],
    *,
    node_index: NodeIndex | None = None,
) -> None:
    for name in nodes(tree, ast.Name, index=node_index):
        if isinstance(name.ctx, (ast.Store, ast.Del)):
            count(_scope(name, parents), name.id)
    for argument in nodes(tree, ast.arg, index=node_index):
        count(_scope(argument, parents), argument.arg)
    _count_import_bindings(tree, parents, count, wildcard_scopes, node_index=node_index)
    for definition in nodes(tree, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, index=node_index):
        parent = parents.get(definition)
        if parent is not None:
            count(_scope(parent, parents), definition.name)
    for handler in nodes(tree, ast.ExceptHandler, index=node_index):
        if handler.name:
            count(_scope(handler, parents), handler.name)
    for pattern in nodes(tree, ast.MatchAs, ast.MatchStar, ast.MatchMapping, index=node_index):
        name = pattern.name if isinstance(pattern, (ast.MatchAs, ast.MatchStar)) else pattern.rest
        if name:
            count(_scope(pattern, parents), name)
    for declaration in nodes(tree, ast.Global, ast.Nonlocal, index=node_index):
        for name in declaration.names:
            count(_scope(declaration, parents), name)


def _query_binding_values(
    tree: ast.Module,
    parents: Mapping[ast.AST, ast.AST],
    binding_values: dict[tuple[int, str], ast.expr],
    *,
    node_index: NodeIndex | None = None,
) -> None:
    for assignment in nodes(tree, ast.Assign, ast.AnnAssign, index=node_index):
        target: ast.expr | None = None
        if isinstance(assignment, ast.Assign) and len(assignment.targets) == 1:
            target = assignment.targets[0]
        elif isinstance(assignment, ast.AnnAssign):
            target = assignment.target
        if not isinstance(target, ast.Name) or assignment.value is None:
            continue
        owner = _scope(assignment, parents)
        if parents.get(assignment) is owner:
            binding_values[id(owner), target.id] = assignment.value


def _record_sql_constructors(
    node: ast.Import | ast.ImportFrom, owner_id: int, constructors: set[_ConstructorImport]
) -> None:
    if isinstance(node, ast.Import):
        _record_sql_module_imports(node, owner_id, constructors)
        return
    if node.level:
        return
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


def _query_architecture_signal(text_value: str, path: Path) -> str | None:
    sql_without_noise = strip_sql_noise(text_value)
    if (
        _QUERY_SHAPE.search(sql_without_noise) is None
        or _CLICKHOUSE_SQL.search(sql_without_noise)
        or _BIGQUERY_SQL.search(sql_without_noise)
        or (is_store_module(path) and analytical_signal(sql_without_noise) is not None)
    ):
        return None
    return _parse_signal(text_value)


def _parse_signal(sql: str) -> str | None:
    import sqlglot  # ruff: ignore[import-outside-top-level] -- parse only SQL that passes cheap ownership and shape gates
    from sqlglot.errors import SqlglotError  # ruff: ignore[import-outside-top-level] -- paired with lazy parser import

    normalized = _COMPOSABLE_HOLE.sub(_SQL_HOLE, sql)
    try:
        for statement in sqlglot.parse(normalized, read="postgres"):
            if statement is not None and (signal := _architecture_signal(statement)) is not None:
                return signal
    except SqlglotError:
        return None
    return None


def _architecture_signal(statement: exp.Expr) -> str | None:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- keep parser startup off unrelated lint runs

    if not isinstance(statement, (exp.Query, exp.Insert, exp.Update, exp.Delete)):
        return None
    maximum_joins = _maximum_query_joins(statement)
    if maximum_joins >= _JOIN_LIMIT:
        return f"SELECT block has {maximum_joins} JOINs (4+ explicit JOINs or comma relations)"
    nested_queries = sum(1 for query in statement.walk() if isinstance(query, (exp.Select, exp.SetOperation)))
    nested_queries -= isinstance(statement, (exp.Select, exp.SetOperation))
    if (derived_signal := _derived_architecture_signal(statement)) is not None:
        return derived_signal
    if nested_queries >= _STAGE_LIMIT:
        return f"Query has {nested_queries} CTE/subquery stages"
    if maximum_joins >= _COMBINED_JOIN_LIMIT and nested_queries >= _COMBINED_STAGE_LIMIT:
        return f"Query combines {maximum_joins} JOINs with {nested_queries} CTE/subquery stages"
    for select in statement.find_all(exp.Select):
        projections = tuple(_expression_args(select, "expressions"))
        joins = tuple(join for join in _expression_args(select, "joins") if isinstance(join, exp.Join))
        if len(projections) >= _WIDE_PROJECTION_LIMIT and len(joins) >= _WIDE_PROJECTION_JOIN_LIMIT:
            return f"Joined query block has {len(projections)} projected expressions"
    return None


def _derived_architecture_signal(statement: exp.Expr) -> str | None:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- keep parser startup off unrelated lint runs

    for select in statement.find_all(exp.Select):
        for join in _expression_args(select, "joins"):
            if not isinstance(join, exp.Join):
                continue
            if (derived := _derived_query(_expression_arg(join, "this"))) is not None and _has_complex_body(derived):
                return "JOIN-derived query combines grouping, HAVING or windowing with joins or nested reads"
        from_clause = _expression_arg(select, "from_")
        if not isinstance(from_clause, exp.From):
            continue
        if (derived := _derived_query(_expression_arg(from_clause, "this"))) is not None and _has_complex_body(derived):
            return "FROM-derived query combines grouping, HAVING or windowing with joins or nested reads"
    return None


def _has_complex_body(query: exp.Query) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- keep parser startup off unrelated lint runs

    if isinstance(query, exp.SetOperation):
        return any(
            isinstance(branch := _expression_arg(query, key), exp.Query)
            and (_has_row_transform(branch) or _has_complex_body(branch))
            for key in ("this", "expression")
        )
    if not isinstance(query, exp.Select):
        return False
    if _has_row_transform(query) and (
        _expression_args(query, "joins") or any(select is not query for select in query.find_all(exp.Select))
    ):
        return True
    for relation in query.find_all(exp.From, exp.Join):
        if relation.parent is not query:
            continue
        child = _derived_query(_expression_arg(relation, "this"))
        if child is not None and (_has_row_transform(child) or _has_complex_body(child)):
            return True
    return False


def _has_row_transform(query: exp.Query) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- keep parser startup off unrelated lint runs

    select = _derived_query(query)
    return isinstance(select, exp.Select) and (
        _expression_arg(select, "group") is not None
        or _expression_arg(select, "having") is not None
        or any(window.parent_select is select for window in select.find_all(exp.Window))
    )


def _maximum_query_joins(statement: exp.Expr) -> int:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- keep parser startup off unrelated lint runs

    return max(
        (
            sum(isinstance(join, exp.Join) for join in _expression_args(select, "joins"))
            for select in statement.find_all(exp.Select)
        ),
        default=0,
    )


def _count_import_bindings(
    tree: ast.Module,
    parents: Mapping[ast.AST, ast.AST],
    count: Callable[[ast.AST, str], None],
    wildcard_scopes: set[int],
    *,
    node_index: NodeIndex | None = None,
) -> None:
    for imported in nodes(tree, ast.Import, ast.ImportFrom, index=node_index):
        owner = _scope(imported, parents)
        for alias in imported.names:
            if alias.name == "*":
                wildcard_scopes.add(id(owner))
                continue
            count(owner, alias.asname or alias.name.split(".")[0])


def _record_sql_module_imports(node: ast.Import, owner_id: int, constructors: set[_ConstructorImport]) -> None:
    for alias in node.names:
        if alias.name == "psycopg.sql":
            constructors.add(_ConstructorImport(owner_id, f"{alias.asname}.SQL" if alias.asname else "psycopg.sql.SQL"))


def _query_review_guidance(text_value: str) -> str:
    coordination = re.search(
        r"\b(?:FOR\s+(?:NO\s+KEY\s+)?UPDATE|FOR\s+SHARE|SKIP\s+LOCKED)\b", text_value, re.IGNORECASE
    )
    return (
        " preserve the atomic statement; review bounds, ordering, and locks, then document its cardinality, "
        "supporting indexes, and production-like plan."
        if coordination is not None
        else " review bounds, ordering, and locks; review cardinality and a production-like query plan, then "
        "review whether repeated read-time reconstruction should become a stable derived fact maintained at "
        "write-time, or otherwise simplify the query or read model when warranted."
    )


def _is_postgres_module(tree: ast.Module, *, node_index: NodeIndex | None = None) -> bool:
    imports = _import_names(tree, node_index=node_index)
    return _has_import_prefix(imports, _POSTGRES_IMPORT_PREFIXES) and not _has_import_prefix(
        imports, _AMBIGUOUS_RELATIONAL_IMPORT_PREFIXES
    )


def _has_import_prefix(imports: frozenset[str], prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(f"{prefix}.") for name in imports for prefix in prefixes)


def _import_names(tree: ast.AST, *, node_index: NodeIndex | None = None) -> frozenset[str]:
    names: set[str] = set()
    for node in nodes(tree, ast.Import, ast.ImportFrom, index=node_index):
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
