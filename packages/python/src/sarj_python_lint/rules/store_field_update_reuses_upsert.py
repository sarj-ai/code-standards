from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
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
from sarj_python_lint.rules._sql import is_store_module
from sarj_python_lint.rules._store_writes import (
    StoreOwners,
    executed_queries,
    method_parameters,
    methods,
    same_type,
    sql_arg,
    sql_args,
    sql_identifier,
    sql_table,
)


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
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
            "The command's fields must resolve from a source-declared class, and the setter and upsert must declare the same result type. SQL composition, inherited fields, dynamic commands, conditional upserts, guarded transitions, arithmetic, joins, CTEs and multiple statements are excluded.",
            "The finding is a consolidation review, not proof that INSERT ON CONFLICT preserves update-only behavior. A missing row must not be created accidentally; omitted fields must not be overwritten by defaults.",
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
            declared = methods(owner)
            upsert = declared.get("upsert")
            contract = _upsert_contract(upsert, owners, context) if upsert is not None else None
            if contract is None:
                continue
            for method in _redundant_updates(declared, contract, context):
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


def _upsert_contract(method: Function, owners: StoreOwners, context: PythonFileContext) -> _UpsertContract | None:
    parameters = method_parameters(method)
    if parameters is None or len(parameters) != 1 or parameters[0].annotation is None:
        return None
    command = owners.annotation(parameters[0].annotation)
    queries = executed_queries(method, context.imports)
    if command is None or len(queries) != 1 or not isinstance(queries[0], exp.Insert):
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
    command_fields = {
        node.target.id
        for node in command[0].body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    keys = _key_columns(sql_args(conflict, "conflict_keys"))
    fields = frozenset(
        column
        for assignment in sql_args(conflict, "expressions")
        if (column := _excluded_field(assignment)) is not None
    )
    if not keys or not fields or not (keys | fields) <= command_fields:
        return None
    return _UpsertContract(table, keys, fields)


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
    declared: dict[str, Function], contract: _UpsertContract, context: PythonFileContext
) -> list[Function]:
    result: list[Function] = []
    for name, method in declared.items():
        if not name.startswith(("set_", "update_")) or not same_type(method.returns, declared["upsert"].returns):
            continue
        queries = executed_queries(method, context.imports)
        if len(queries) == 1 and isinstance(queries[0], exp.Update) and _plain_update(queries[0], contract):
            result.append(method)
    return result


def _plain_update(query: exp.Update, contract: _UpsertContract) -> bool:
    if sql_table(sql_arg(query, "this")) != contract.table or sql_arg(query, "with_") or sql_arg(query, "from_"):
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
        if sql_identifier(left) == "updated_at" and isinstance(right, exp.CurrentTimestamp):
            continue
        if not isinstance(right, exp.Placeholder):
            return frozenset()
        name = sql_identifier(left)
        if name is None:
            return frozenset()
        assigned.add(name)
    return frozenset(assigned)


def _bound_column(node: exp.Expr) -> str | None:
    left, right = sql_arg(node, "this"), sql_arg(node, "expression")
    return (
        sql_identifier(left)
        if isinstance(node, exp.EQ) and isinstance(left, exp.Column) and isinstance(right, exp.Placeholder)
        else None
    )
