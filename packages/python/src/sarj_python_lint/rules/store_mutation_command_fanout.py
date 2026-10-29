from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, final, override

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
from sarj_python_lint.rules._paths import is_test_path
from sarj_python_lint.rules._resource_provenance import import_name_for_binding
from sarj_python_lint.rules._sql import is_store_module
from sarj_python_lint.rules._store_sql import StoreQuery, relation_key, sql_child, store_queries
from sarj_python_lint.rules._store_writes import methods, own_nodes
from sarj_python_lint.rules.store_field_update_reuses_upsert import StoreFieldUpdateReusesUpsert


if TYPE_CHECKING:
    from sarj_python_lint._file_context import PythonFileContext
    from sarj_python_lint.rules._store_writes import Function


_BAD = """from psycopg import AsyncCursor
class ItemStore:
    def __init__(self, cursor: AsyncCursor):
        self.cursor = cursor
    async def upsert(self, item):
        await self.cursor.execute('INSERT INTO item(id, name) VALUES(%s, %s) ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name', (item.id, item.name))
    async def set_name_before_start(self, key, name):
        await self.cursor.execute('UPDATE item SET name=%s WHERE id=%s AND started_at IS NULL', (name, key))
"""


@final
class StoreMutationCommandFanout(Rule):
    id = "store-mutation-command-fanout"
    code = "SARJ546"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="Review per-field store mutations beside an existing model write command.",
        rationale="Per-field mutation entry points beside a model upsert can scatter write validation and concurrency policy. A smaller typed command surface makes those contracts easier to review together.",
        remediation="Review whether these methods can share a typed mutation command or internal write implementation. Preserve update-only and missing-row behavior, authorization, omission versus null, and guarded transitions. Do not replace a conditional UPDATE with an insert-capable upsert; model distinct transitions explicitly when they must stay separate.",
        category=RuleCategory.ARCHITECTURE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "This is API consolidation advice, not proof that writes are equivalent. Checks non-test store modules with an upsert-named command reaching an INSERT and a set_-named direct UPDATE of the same exactly qualified relation. A bounded direct same-class helper call can establish that INSERT target; the command name does not prove conflict handling. Dynamic relation names, inherited upserts, unknown decorators or receivers, unknown owners and unrelated relations abstain. Duplicate or overwritten declarations and direct method attribute assignments are excluded; indirect runtime monkey-patching remains unsupported.",
            "Also reviews source-visible abstract set_ methods declared beside an abstract upsert in a store interface. The explicit setter API spelling triggers this interface policy; it does not prove the method is redundant or identify its implementation.",
            "The precise ordinary-field duplication owner SARJ517 takes precedence at the same method. Guarded and multi-statement operations can still be reported for review, but their transaction and concurrency contracts must be retained. One diagnostic is emitted per method, with no automatic edit.",
        ),
        examples=(
            RuleExample(
                example_id="conditional-setter",
                title="Review a separate guarded setter",
                outcome=ExampleOutcome.MATCH,
                files=(ExampleFile.python("app/item_store.py", _BAD),),
                focus_path=PurePosixPath("app/item_store.py"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="different-relation",
                title="Different relation ownership is preserved",
                outcome=ExampleOutcome.NO_MATCH,
                files=(ExampleFile.python("app/item_store.py", _BAD.replace("UPDATE item SET", "UPDATE other SET")),),
                focus_path=PurePosixPath("app/item_store.py"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if context.generated or context.tree is None or is_test_path(context.path) or not is_store_module(context.path):
            return []
        from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- native writes only.

        queries = tuple(store_queries(context))
        declared = _declared_methods(context)
        upserts = _upsert_relations(queries, declared, context)
        selected: set[Function] = set()
        for query in queries:
            if (
                query.method is None
                or query.owner is None
                or not query.method.name.startswith("set_")
                or declared.get(query.owner, {}).get(query.method.name) is not query.method
                or not _instance_method(query.method, context)
            ):
                continue
            if isinstance(query.statement, exp.Update) and relation_key(
                sql_child(query.statement, "this")
            ) in upserts.get(query.owner, set()):
                selected.add(query.method)
        selected.update(_abstract_setters(context, declared))
        precise = {finding.line for finding in StoreFieldUpdateReusesUpsert().check_context(context)}
        return [
            Diagnostic(
                context.path,
                method.lineno,
                method.col_offset + 1,
                self.code,
                f"Review `{method.name}` beside the model upsert; consolidate the typed mutation surface where possible while preserving its missing-row, authorization, transaction and concurrency contract.",
                severity=Severity.WARNING,
            )
            for method in sorted(selected, key=lambda node: (node.lineno, node.col_offset))
            if method.lineno not in precise
        ]


def _upsert_relations(
    queries: tuple[StoreQuery, ...], declared: dict[ast.ClassDef, dict[str, Function]], context: PythonFileContext
) -> dict[ast.ClassDef, set[tuple[str, ...]]]:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- parsed INSERT ownership only.

    upserts: dict[ast.ClassDef, set[tuple[str, ...]]] = {}
    reachable = {owner: _upsert_methods(value, context) for owner, value in declared.items()}
    for query in queries:
        if query.owner is None or query.method is None:
            continue
        if query.method not in reachable.get(query.owner, set()):
            continue
        statement = query.statement
        if not isinstance(statement, exp.Insert):
            continue
        relation = sql_child(statement, "this")
        relation = sql_child(relation, "this") if isinstance(relation, exp.Schema) else relation
        if (key := relation_key(relation)) is not None:
            upserts.setdefault(query.owner, set()).add(key)
    return upserts


def _abstract_setters(context: PythonFileContext, owners: dict[ast.ClassDef, dict[str, Function]]) -> set[Function]:
    result: set[Function] = set()
    for declared in owners.values():
        upsert = declared.get("upsert")
        if upsert is None or not _abstract(upsert, context):
            continue
        result.update(
            method for name, method in declared.items() if name.startswith("set_") and _abstract(method, context)
        )
    return result


def _abstract(method: Function, context: PythonFileContext) -> bool:
    return _instance_method(method, context) and any(
        _runtime_import_name(decorator, context) == "abc.abstractmethod" for decorator in method.decorator_list
    )


def _upsert_methods(declared: dict[str, Function], context: PythonFileContext) -> set[Function]:
    upsert = declared.get("upsert")
    if upsert is None or not _instance_method(upsert, context):
        return set()
    reachable = {upsert}
    for _ in range(3):
        discovered = {
            declared[node.func.attr]
            for method in reachable
            for node in own_nodes(method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
            and node.func.attr in declared
            and _instance_method(declared[node.func.attr], context)
            and context.static_resource_provenance.runtime_binding("self", node)
            is [*method.args.posonlyargs, *method.args.args][0]
        }
        if discovered <= reachable:
            break
        reachable.update(discovered)
    return reachable


def _declared_methods(context: PythonFileContext) -> dict[ast.ClassDef, dict[str, Function]]:
    declared = {
        owner: methods(owner)
        for owner in context.nodes(ast.ClassDef)
        if not owner.keywords
        and all(
            _runtime_import_name(decorator, context) in {"typing.final", "typing_extensions.final"}
            for decorator in owner.decorator_list
        )
    }
    for node in context.nodes(ast.Attribute):
        if not isinstance(node.ctx, ast.Store | ast.Del) or not isinstance(node.value, ast.Name):
            continue
        binding = context.static_resource_provenance.runtime_binding(node.value.id, node)
        if isinstance(binding, ast.ClassDef) and binding in declared:
            declared[binding].pop(node.attr, None)
    return declared


def _instance_method(method: Function, context: PythonFileContext) -> bool:
    positional = [*method.args.posonlyargs, *method.args.args]
    return (
        bool(positional)
        and positional[0].arg == "self"
        and all(
            _runtime_import_name(decorator, context)
            in {
                "abc.abstractmethod",
                "typing.override",
                "typing_extensions.override",
                "typing.final",
                "typing_extensions.final",
            }
            for decorator in method.decorator_list
        )
    )


def _runtime_import_name(expression: ast.expr, context: PythonFileContext) -> str | None:
    root = expression
    while isinstance(root, ast.Attribute):
        root = root.value
    provenance = context.static_resource_provenance
    if (
        not isinstance(root, ast.Name)
        or provenance.wildcard
        or provenance.dynamic_namespace
        or root.id in provenance.mutated
    ):
        return None
    binding = provenance.runtime_binding(root.id, expression)
    return (
        import_name_for_binding(expression, binding, context.parents.get(binding))
        if isinstance(binding, ast.alias)
        else None
    )
