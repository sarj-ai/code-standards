from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, final, override

from sqlglot import exp

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
from sarj_python_lint.rules._annotation_semantics import AnnotationSemantics, scope_bound_names
from sarj_python_lint.rules._sql import is_store_module
from sarj_python_lint.rules._store_writes import (
    StoreOwners,
    executed_queries,
    method_parameters,
    methods,
    own_nodes,
    same_type,
    sql_arg,
    sql_args,
    sql_identifier,
    sql_table,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._imports import ImportIndex
    from sarj_python_lint.rules._store_writes import Function


_BAD = "from pydantic import BaseModel\nclass UserInput(BaseModel):\n    id: str\n    name: str\nclass UserStore:\n    async def upsert(self, data: UserInput) -> User:\n        await self.cursor.execute('INSERT INTO users (id, name) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name', (data.id, data.name))\n    async def set_name(self, id_: str, name: str) -> User:\n        await self.cursor.execute('UPDATE users SET name = %s WHERE id = %s', (name, id_))\n"


@final
class StoreFieldUpdateReusesUpsert(Rule):
    id = "store-field-update-reuses-upsert"
    code = "SARJ517"
    documentation: ClassVar[RuleDocumentation | None] = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="A plain field UPDATE duplicates fields already writable through the store's upsert command.",
        rationale="Independent per-field SQL methods duplicate write policy and can drift from the existing model command's validation, conflict handling and timestamps.",
        remediation="Prefer one typed model command for ordinary writable fields. Reuse or extend its write implementation while preserving update-only, missing-row, omission/null, authorization and concurrency contracts; retain domain transitions as separate operations.",
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only a single literal PostgreSQL UPDATE on the same table as a literal upsert is checked, with equality predicates exactly matching the conflict key and direct bound-value assignments already covered by EXCLUDED field assignments.",
            "The command's fields must resolve from a source-declared class and flow directly into one INSERT VALUES row through literal positional or named parameters. Shadowed annotations, explicit descriptors and class keywords do not prove writable fields. The setter and upsert must declare the same result type, RETURNING projection and updated_at policy. SQL composition, inherited fields, dynamic commands, conditional or transformed upserts, unknown decorators, Python branching, arithmetic, joins, CTEs and multiple statements are excluded.",
            "The finding is a consolidation review, not proof that INSERT ON CONFLICT preserves update-only behavior. A missing row must not be created accidentally; omitted fields must not be overwritten by defaults.",
            "Context-manager behavior and other surrounding effects are not proven equivalent. Share ordinary write implementation behind existing authorization or transaction wrappers while preserving those contracts.",
            "Generated and test sources are excluded. There is no automatic replacement and no requirement to expose immutable or privileged model fields.",
        ),
        examples=(
            RuleExample(
                example_id="duplicate-field-update",
                title="Consolidate an ordinary field write",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/user_store.py", _BAD),),
                focus_path=PurePosixPath("app/user_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="guarded-field-update",
                title="Keep an update with a distinct concurrency contract",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.python(
                        "app/user_store.py",
                        _BAD.replace("WHERE id = %s'", "WHERE id = %s AND version = %s'")
                        .replace("name: str) -> User:", "name: str, version: int) -> User:")
                        .replace("(name, id_)", "(name, id_, version)"),
                    ),
                ),
                focus_path=PurePosixPath("app/user_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.generated
            or not is_store_module(context.path)
            or "upsert" not in context.symbol_source
            or context.tree is None
        ):
            return []
        owners = StoreOwners(context)
        findings: list[Diagnostic] = []
        for owner in (node for node in context.tree.body if isinstance(node, ast.ClassDef)):
            if owner.keywords:
                continue
            declared = methods(owner)
            upsert = declared.get("upsert")
            contract = _upsert_contract(upsert, owners, context) if upsert is not None else None
            if contract is None:
                continue
            for method in _redundant_updates(declared, contract, context, owners):
                name = method.name
                if is_suppressed(context.source_lines, method.lineno, self.code):
                    continue
                findings.append(
                    Diagnostic(
                        path=context.path,
                        line=method.lineno,
                        col=method.col_offset + 1,
                        code=self.code,
                        severity=Severity.WARNING,
                        message=f"`{name}` repeats fields already writable by `upsert`; consolidate the ordinary write command while preserving update-only/missing-row, omission/null, authorization and concurrency behavior.",
                    )
                )
        return findings


@dataclass(frozen=True)
class _UpsertContract:
    table: tuple[str | None, ...]
    keys: frozenset[str]
    fields: frozenset[str]
    updated_at_policy: exp.Expr | None
    returning: exp.Expr | None


def _upsert_contract(method: Function, owners: StoreOwners, context: PythonFileContext) -> _UpsertContract | None:
    parameters = method_parameters(method)
    if (
        parameters is None
        or len(parameters) != 1
        or parameters[0].annotation is None
        or not _ordinary_method(method, context)
    ):
        return None
    command = owners.annotation(parameters[0].annotation)
    queries = executed_queries(method, context.imports)
    if command is None or command[0].keywords or len(queries) != 1 or not isinstance(queries[0], exp.Insert):
        return None
    query = queries[0]
    conflict = sql_arg(query, "conflict")
    schema = sql_arg(query, "this")
    table = sql_table(sql_arg(schema, "this")) if isinstance(schema, exp.Schema) else None
    if (
        table is None
        or not isinstance(conflict, exp.OnConflict)
        or sql_arg(conflict, "where")
        or sql_arg(conflict, "index_predicate")
        or sql_arg(query, "with_")
    ):
        return None
    command_fields = _command_fields(*command)
    keys = _key_columns(sql_args(conflict, "conflict_keys"))
    fields = frozenset(
        column
        for assignment in sql_args(conflict, "expressions")
        if (column := _excluded_field(assignment)) is not None
    )
    timestamps = tuple(
        assignment for assignment in sql_args(conflict, "expressions") if _timestamp_assignment(assignment)
    )
    if len(timestamps) > 1:
        return None
    if (
        not keys
        or not fields
        or len(fields) + len(timestamps) != len(sql_args(conflict, "expressions"))
        or not (keys | fields) <= command_fields
        or not (keys | fields) <= _command_insert_fields(method, parameters[0], query, owners)
    ):
        return None
    timestamp_policy = sql_arg(timestamps[0], "expression") if timestamps else None
    return _UpsertContract(table, keys, fields, timestamp_policy, sql_arg(query, "returning"))


def _command_fields(owner: ast.ClassDef, imports: ImportIndex) -> frozenset[str]:
    declared: set[str] = set()
    shadowed: set[str] = set()
    for statement in owner.body:
        if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
            shadowed.update(scope_bound_names([statement]))
            continue
        name = statement.target.id
        if name in declared:
            shadowed.add(name)
        declared.add(name)
        if not _instance_field(statement.annotation, imports) or _descriptor_default(statement.value, imports):
            shadowed.add(name)
    return frozenset(declared - shadowed)


def _descriptor_default(value: ast.expr | None, imports: ImportIndex) -> bool:
    if not isinstance(value, ast.Call):
        return False
    if imports.resolved_qualified_name(value.func) in {
        "builtins.property",
        "builtins.classmethod",
        "builtins.staticmethod",
    }:
        return True
    return (
        isinstance(value.func, ast.Name)
        and value.func.id in {"property", "classmethod", "staticmethod"}
        and imports.builtin_is_unshadowed(value.func.id)
    )


def _instance_field(annotation: ast.expr, imports: ImportIndex) -> bool:
    parsed = AnnotationSemantics(imports, MappingProxyType({})).parse(annotation)
    return parsed is not None and not any(
        isinstance(node, ast.Subscript)
        and imports.resolved_qualified_name(node.value)
        in {"typing.ClassVar", "typing_extensions.ClassVar", "dataclasses.InitVar"}
        for node in own_nodes(parsed)
    )


def _ordinary_method(method: Function, context: PythonFileContext) -> bool:
    if any(
        context.imports.resolved_qualified_name(decorator) not in {"typing.override", "typing_extensions.override"}
        for decorator in method.decorator_list
    ):
        return False
    return not any(
        isinstance(
            node,
            ast.If
            | ast.IfExp
            | ast.Match
            | ast.Try
            | ast.TryStar
            | ast.For
            | ast.AsyncFor
            | ast.While
            | ast.Raise
            | ast.Assert
            | ast.BoolOp
            | ast.comprehension,
        )
        for statement in method.body
        if not isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        for node in own_nodes(statement)
    )


def _execute_call(method: Function) -> ast.Call | None:
    calls = [
        node
        for statement in method.body
        if not isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        for node in own_nodes(statement)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "executemany"}
    ]
    if len(calls) != 1:
        return None
    call = calls[0]
    return call if isinstance(call.func, ast.Attribute) and call.func.attr == "execute" else None


def _bound_values(call: ast.Call) -> ast.expr | None:
    match call.args:
        case [_, parameters] if not any(keyword.arg == "params" for keyword in call.keywords):
            return parameters
        case [_]:
            return next((keyword.value for keyword in call.keywords if keyword.arg == "params"), None)
        case _:
            return None


def _command_insert_fields(
    method: Function, parameter: ast.arg, query: exp.Insert, owners: StoreOwners
) -> frozenset[str]:
    row = _insert_row(query)
    call = _execute_call(method)
    bound = _bound_values(call) if call is not None else None
    if row is None or bound is None:
        return frozenset()
    columns, expressions = row
    arguments = _insert_arguments(bound, expressions)
    if arguments is None:
        return frozenset()
    return frozenset(
        name
        for column, value in zip(columns, arguments, strict=True)
        if (name := sql_identifier(column)) is not None
        and isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.attr == name
        and owners.provenance.binding(value.value.id, value) is parameter
        and value.value.id not in owners.provenance.mutated
    )


def _insert_row(query: exp.Insert) -> tuple[tuple[exp.Expr, ...], tuple[exp.Expr, ...]] | None:
    schema = sql_arg(query, "this")
    values = sql_arg(query, "expression")
    rows = sql_args(values, "expressions") if isinstance(values, exp.Values) else ()
    columns = sql_args(schema, "expressions") if isinstance(schema, exp.Schema) else ()
    if len(rows) != 1 or not isinstance(rows[0], exp.Tuple):
        return None
    expressions = sql_args(rows[0], "expressions")
    return (columns, expressions) if len(columns) == len(expressions) else None


def _insert_arguments(bound: ast.expr, expressions: tuple[exp.Expr, ...]) -> tuple[ast.expr, ...] | None:
    if isinstance(bound, ast.Tuple | ast.List):
        if len(bound.elts) != len(expressions):
            return None
        if any(not isinstance(value, exp.Placeholder) or sql_arg(value, "this") is not None for value in expressions):
            return None
        return tuple(bound.elts)
    return _named_insert_arguments(bound, expressions) if isinstance(bound, ast.Dict) else None


def _named_insert_arguments(bound: ast.Dict, expressions: tuple[exp.Expr, ...]) -> tuple[ast.expr, ...] | None:
    names = _placeholder_names(expressions)
    bindings = {
        key.value: value
        for key, value in zip(bound.keys, bound.values, strict=True)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    if names is None or len(bindings) != len(bound.keys) or any(name not in bindings for name in names):
        return None
    return tuple(bindings[name] for name in names)


def _placeholder_names(expressions: tuple[exp.Expr, ...]) -> tuple[str, ...] | None:
    names: list[str] = []
    for expression in expressions:
        if not isinstance(expression, exp.Placeholder):
            return None
        name = sql_arg(expression, "this")
        if not isinstance(name, exp.Identifier):
            return None
        names.append(name.name)
    return tuple(names)


def _key_columns(expressions: tuple[exp.Expr, ...]) -> frozenset[str]:
    columns = [sql_arg(node, "this") if isinstance(node, exp.Ordered) else node for node in expressions]
    names = [sql_identifier(node) if isinstance(node, exp.Column) else None for node in columns]
    return frozenset(name for name in names if name is not None) if None not in names else frozenset()


def _excluded_field(assignment: exp.Expr) -> str | None:
    left, right = sql_arg(assignment, "this"), sql_arg(assignment, "expression")
    if not isinstance(assignment, exp.EQ) or not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
        return None
    return (
        sql_identifier(left)
        if sql_identifier(sql_arg(right, "table")) == "excluded" and sql_identifier(left) == sql_identifier(right)
        else None
    )


def _redundant_updates(
    declared: dict[str, Function], contract: _UpsertContract, context: PythonFileContext, owners: StoreOwners
) -> list[Function]:
    result: list[Function] = []
    for name, method in declared.items():
        if (
            not name.startswith(("set_", "update_"))
            or not same_type(method.returns, declared["upsert"].returns)
            or isinstance(method, ast.AsyncFunctionDef) != isinstance(declared["upsert"], ast.AsyncFunctionDef)
            or not _ordinary_method(method, context)
            or not _direct_setter_parameters(method, owners)
        ):
            continue
        queries = executed_queries(method, context.imports)
        if len(queries) == 1 and isinstance(queries[0], exp.Update) and _plain_update(queries[0], contract):
            result.append(method)
    return result


def _direct_setter_parameters(method: Function, owners: StoreOwners) -> bool:
    call = _execute_call(method)
    bound = _bound_values(call) if call is not None else None
    parameters = method_parameters(method)
    if parameters is None:
        return False
    if isinstance(bound, ast.Tuple | ast.List):
        values = bound.elts
    elif isinstance(bound, ast.Dict) and all(isinstance(key, ast.Constant) for key in bound.keys):
        values = bound.values
    else:
        return False
    return bool(values) and all(
        isinstance(value, ast.Name) and owners.provenance.binding(value.id, value) in parameters for value in values
    )


def _plain_update(query: exp.Update, contract: _UpsertContract) -> bool:
    table = sql_arg(query, "this")
    if (
        sql_table(table) != contract.table
        or (isinstance(table, exp.Table) and table.args.get("only"))
        or sql_arg(query, "with_")
        or sql_arg(query, "from_")
    ):
        return False
    timestamps = tuple(
        sql_arg(assignment, "expression")
        for assignment in sql_args(query, "expressions")
        if _timestamp_assignment(assignment)
    )
    if len(timestamps) > 1:
        return False
    timestamp_policy = timestamps[0] if timestamps else None
    if sql_arg(query, "returning") != contract.returning or timestamp_policy != contract.updated_at_policy:
        return False
    where = sql_arg(query, "where")
    if not isinstance(where, exp.Where):
        return False
    condition = sql_arg(where, "this")
    predicates = (
        tuple(condition.flatten()) if isinstance(condition, exp.And) else (condition,) if condition is not None else ()
    )
    names = tuple(_bound_column(node) for node in predicates)
    if not names or None in names or len(names) != len(contract.keys):
        return False
    if frozenset(names) != contract.keys:
        return False
    assigned = _assigned_fields(query)
    return bool(assigned) and assigned <= contract.fields


def _assigned_fields(query: exp.Update) -> frozenset[str]:
    assigned: set[str] = set()
    for assignment in sql_args(query, "expressions"):
        left, right = sql_arg(assignment, "this"), sql_arg(assignment, "expression")
        if not isinstance(assignment, exp.EQ) or not isinstance(left, exp.Column):
            return frozenset()
        if _timestamp_assignment(assignment):
            continue
        if not isinstance(right, exp.Placeholder):
            return frozenset()
        name = sql_identifier(left)
        if name is None:
            return frozenset()
        assigned.add(name)
    return frozenset(assigned)


def _timestamp_assignment(assignment: exp.Expr) -> bool:
    left, right = sql_arg(assignment, "this"), sql_arg(assignment, "expression")
    return (
        isinstance(assignment, exp.EQ)
        and sql_identifier(left) == "updated_at"
        and isinstance(right, exp.CurrentTimestamp)
    )


def _bound_column(node: exp.Expr) -> str | None:
    left, right = sql_arg(node, "this"), sql_arg(node, "expression")
    return (
        sql_identifier(left)
        if isinstance(node, exp.EQ) and isinstance(left, exp.Column) and isinstance(right, exp.Placeholder)
        else None
    )
