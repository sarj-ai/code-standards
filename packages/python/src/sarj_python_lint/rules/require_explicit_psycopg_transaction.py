from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar, Literal, final, override

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

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
    is_suppressed,
)
from sarj_python_lint.rules._imports import ImportIndex
from sarj_python_lint.rules._paths import is_test_path, is_test_support_path
from sarj_python_lint.rules._sql import sql_string_value


if TYPE_CHECKING:
    from collections.abc import Iterator

    from sarj_python_lint._file_context import PythonFileContext


type _Function = ast.FunctionDef | ast.AsyncFunctionDef
type _Kind = Literal["pool", "connection", "cursor"]
_MUTATIONS = (exp.Insert, exp.Update, exp.Delete, exp.Merge)
_BAD = 'from psycopg_pool import AsyncConnectionPool\nasync def save(pool: AsyncConnectionPool):\n    async with pool.connection() as conn:\n        await conn.execute("SELECT id FROM items FOR UPDATE")\n        await conn.execute("UPDATE items SET n = 1")\n'
_GOOD = _BAD.replace("as conn:", "as conn, conn.transaction():")


@final
class RequireExplicitPsycopgTransaction(Rule):
    id = "require-explicit-psycopg-transaction"
    code = "SARJ462"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Make Psycopg locking reads and related writes explicitly transactional.",
        rationale="Pool checkout does not start a transaction in autocommit mode. Locks can expire before use and earlier writes can survive a later failure.",
        remediation="Enclose the complete atomic operation in the same connection's transaction() context, or use one atomic SQL statement. Document intentionally independent writes with an exact suppression.",
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Reports import-proven Psycopg connections and cursors from typed parameters or constructor-injected pools. Dynamic factories, interprocedural SQL, and untyped ownership are not inferred.",
            "Inspects literal SQL, simple local/module constants, and psycopg.sql.SQL wrappers. Dynamic SQL and unsupported SQL syntax are excluded.",
            "A locking SELECT followed by a write on the same connection outside transaction() is reported; a single statement containing a mutation is treated as atomic. Multiple writes on a reachable local path are a warning because independent writes can be intentional.",
            "Loops, exception handlers, match statements, comprehensions, and nested closures are not analyzed as execution paths. Manual BEGIN/commit protocols are not inferred. Tests, support fixtures, and generated files are excluded.",
            "The rule cannot prove isolation level, database constraints, or application-level atomicity; fault-injection integration tests remain necessary.",
        ),
        examples=(
            RuleExample(
                example_id="unprotected-lock",
                title="A pool checkout alone does not retain a lock",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("repository.py", _BAD),),
                focus_path=PurePosixPath("repository.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-lock-transaction",
                title="Retain locks for the atomic operation",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("repository.py", _GOOD),),
                focus_path=PurePosixPath("repository.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            "execute" not in context.source
            or context.generated
            or is_test_path(context.path)
            or is_test_support_path(context.path)
        ):
            return []
        tree = context.tree
        if tree is None:
            return []
        imports = ImportIndex.from_tree(tree, module_scope_only=True)
        constants = _constants(tree.body)
        findings: dict[int, ast.Call] = {}
        for function, attributes in _functions(tree.body, imports):
            bindings = attributes | _parameters(function, imports)
            parameter_names = {
                arg.arg for arg in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
            }
            analysis = _Analysis(
                imports, {name: value for name, value in constants.items() if name not in parameter_names}, findings
            )
            analysis.block(function.body, _State(bindings=bindings))
        return [
            Diagnostic(
                path=context.path,
                line=node.lineno,
                col=node.col_offset + 1,
                code=self.code,
                severity=Severity.WARNING,
                message="Locking read or multiple writes without a shared explicit transaction; wrap the atomic operation in this connection's transaction() context.",
            )
            for node in sorted(findings.values(), key=lambda item: (item.lineno, item.col_offset))
            if not is_suppressed(context.source_lines, node.lineno, self.code)
        ]


@dataclass(frozen=True)
class _Binding:
    kind: _Kind
    connection: int


@dataclass
class _State:
    bindings: dict[str, _Binding] = field(default_factory=dict)
    writes: set[int] = field(default_factory=set)
    locks: dict[int, ast.Call] = field(default_factory=dict)
    transactions: set[int] = field(default_factory=set)
    constants: dict[str, ast.expr] = field(default_factory=dict)

    def copy(self) -> _State:
        return _State(
            bindings=self.bindings.copy(),
            writes=self.writes.copy(),
            locks=self.locks.copy(),
            transactions=self.transactions.copy(),
            constants=self.constants.copy(),
        )


def _key(node: ast.expr) -> str:
    return ast.dump(node, include_attributes=False)


def _parameters(function: _Function, imports: ImportIndex) -> dict[str, _Binding]:
    return {
        _key(ast.Name(id=arg.arg, ctx=ast.Load())): _Binding(kind, id(arg))
        for arg in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        if (kind := _annotation(arg.annotation, imports)) is not None
    }


def _annotation(node: ast.expr | None, imports: ImportIndex) -> _Kind | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return None
    if isinstance(node, ast.Subscript):
        node = node.value
    if node is None:
        return None
    if imports.resolved_symbol(node, sources=frozenset({"psycopg_pool"})) in {"AsyncConnectionPool", "ConnectionPool"}:
        return "pool"
    if imports.resolved_symbol(node, sources=frozenset({"psycopg"})) in {"AsyncConnection", "Connection"}:
        return "connection"
    return None


def _functions(statements: list[ast.stmt], imports: ImportIndex) -> Iterator[tuple[_Function, dict[str, _Binding]]]:
    for statement in statements:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
            yield statement, {}
        elif isinstance(statement, ast.ClassDef):
            attributes = _class_bindings(statement, imports)
            for method in statement.body:
                if isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield method, attributes


def _class_bindings(owner: ast.ClassDef, imports: ImportIndex) -> dict[str, _Binding]:
    constructor = next(
        (method for method in owner.body if isinstance(method, ast.FunctionDef) and method.name == "__init__"), None
    )
    if constructor is None:
        return {}
    parameters = _parameters(constructor, imports)
    attributes: dict[str, _Binding] = {}
    for assignment in constructor.body:
        if not isinstance(assignment, ast.Assign):
            continue
        binding = parameters.get(_key(assignment.value))
        if binding is None:
            continue
        for target in assignment.targets:
            if isinstance(target, ast.Attribute):
                attributes[_load_key(target)] = binding
    return attributes


def _load_key(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return _key(ast.Name(id=node.id, ctx=ast.Load()))
    if isinstance(node, ast.Attribute):
        return _key(ast.Attribute(value=node.value, attr=node.attr, ctx=ast.Load()))
    return _key(node)


def _constants(statements: list[ast.stmt]) -> dict[str, ast.expr]:
    values: dict[str, ast.expr] = {}
    for statement in statements:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name) and statement.value:
            values[statement.target.id] = statement.value
    return values


@dataclass
class _Analysis:
    imports: ImportIndex
    constants: dict[str, ast.expr]
    findings: dict[int, ast.Call]

    def block(self, statements: list[ast.stmt], state: _State) -> _State | None:
        for statement in statements:
            match statement:
                case ast.With() | ast.AsyncWith():
                    result = self.with_block(statement, state)
                case ast.If():
                    result = self.branches(statement, state)
                case ast.Return() | ast.Raise():
                    self.executions(statement, state)
                    return None
                case ast.Expr() | ast.Assign() | ast.AnnAssign():
                    self.simple(statement, state)
                    result = state
                case ast.Pass():
                    result = state
                case _:
                    # Unsupported control flow can rebind names or terminate; do not guess across it.
                    result = _State(transactions=state.transactions.copy())
            if result is None:
                return None
            state = result
        return state

    def with_block(self, statement: ast.With | ast.AsyncWith, state: _State) -> _State | None:
        prior_transactions = state.transactions.copy()
        for item in statement.items:
            call = item.context_expr
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                binding = state.bindings.get(_key(call.func.value))
                if binding and call.func.attr == "transaction" and binding.kind == "connection":
                    state.transactions.add(binding.connection)
            if item.optional_vars:
                self.bind(item.optional_vars, call, state)
        result = self.block(statement.body, state)
        if result is not None:
            result.transactions = prior_transactions
        return result

    def branches(self, statement: ast.If, state: _State) -> _State | None:
        if isinstance(statement.test, ast.Constant):
            return self.block(statement.body if statement.test.value else statement.orelse, state)
        left = self.block(statement.body, state.copy())
        right = self.block(statement.orelse, state.copy())
        if left is None:
            return right
        if right is None:
            return left
        return _State(
            bindings={key: value for key, value in left.bindings.items() if right.bindings.get(key) == value},
            writes=left.writes | right.writes,
            locks=left.locks | right.locks,
            transactions=left.transactions & right.transactions,
            constants={key: value for key, value in left.constants.items() if right.constants.get(key) is value},
        )

    def simple(self, statement: ast.stmt, state: _State) -> None:
        self.executions(statement, state)
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                self.bind(target, statement.value, state)
        elif isinstance(statement, ast.AnnAssign) and statement.value:
            self.bind(statement.target, statement.value, state)

    def bind(self, target: ast.expr, value: ast.expr, state: _State) -> None:
        binding = state.bindings.get(_key(value))
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
            parent = state.bindings.get(_key(value.func.value))
            if parent and parent.kind == "pool" and value.func.attr == "connection":
                binding = _Binding("connection", id(value))
            elif parent and parent.kind == "connection" and value.func.attr == "cursor":
                binding = _Binding("cursor", parent.connection)
        key = _load_key(target)
        state.bindings.pop(key, None)
        if binding:
            state.bindings[key] = binding
        if isinstance(target, ast.Name):
            state.constants[target.id] = value

    def executions(self, statement: ast.stmt, state: _State) -> None:
        for node in _eager_nodes(statement):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr not in {"execute", "executemany"}
            ):
                continue
            binding = state.bindings.get(_key(node.func.value))
            if not binding or binding.kind == "pool" or binding.connection in state.transactions or not node.args:
                continue
            sql = self.sql(node.args[0], state, frozenset())
            if sql is None:
                continue
            effects = _sql_effects(sql)
            if effects.mutation and (binding.connection in state.writes or binding.connection in state.locks):
                self.findings.setdefault(binding.connection, state.locks.get(binding.connection, node))
            if effects.locking and not effects.mutation:
                state.locks.setdefault(binding.connection, node)
            if effects.mutation:
                state.writes.add(binding.connection)

    def sql(self, node: ast.expr, state: _State, seen: frozenset[str]) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in seen:
                return None
            value = state.constants.get(node.id, self.constants.get(node.id))
            return self.sql(value, state, seen | {node.id}) if value else None
        if isinstance(node, ast.Call):
            if self.imports.resolves(node.func, sources=frozenset({"psycopg.sql"}), symbol="SQL") and node.args:
                return self.sql(node.args[0], state, seen)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "format":
                return self.sql(node.func.value, state, seen)
            return None
        return sql_string_value(node)


def _eager_nodes(node: ast.AST) -> Iterator[ast.AST]:
    if isinstance(
        node, ast.Lambda | ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp | ast.IfExp | ast.BoolOp
    ):
        return
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _eager_nodes(child)


@dataclass(frozen=True)
class _SqlEffects:
    mutation: bool
    locking: bool


def _sql_effects(sql: str) -> _SqlEffects:
    try:
        queries = sqlglot.parse(sql, read="postgres")
    except SqlglotError:
        return _SqlEffects(mutation=False, locking=False)
    mutation = False
    locking = False
    for query in queries:
        if query is not None:
            mutation = mutation or query.find(*_MUTATIONS) is not None
            locking = locking or query.find(exp.Lock) is not None
    return _SqlEffects(mutation=mutation, locking=locking)
