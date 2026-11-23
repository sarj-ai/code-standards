from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import PurePosixPath
import re
import tomllib
from typing import TYPE_CHECKING, TypeGuard, final, override

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
from sarj_python_lint.rules._store_sql import relation_key, sql_child, sql_children, store_queries


if TYPE_CHECKING:
    import ast
    from pathlib import Path

    from sqlglot import exp

    from sarj_python_lint._file_context import PythonFileContext


_MANIFEST = ".sarj-standards.toml"
_HOLE = "__sarj_store_sql_hole__"
_COLUMN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*")
_MAX_ANCESTORS = 24

_CONFIG = '[python.lifecycle-update-requires-state-guard]\nlifecycle_columns = ["task.status"]\n'
_STORE = """from psycopg import AsyncCursor


class TaskStore:
    def __init__(self, cursor: AsyncCursor):
        self.cursor = cursor

    async def set_many_to_status(self, task_ids, status):
        await self.cursor.execute(
            "UPDATE task SET status = %s, updated_at = NOW() WHERE id = ANY(%s){guard}",
            (status, task_ids),
        )
"""


def _example(example_id: str, title: str, guard: str, *, matches: bool, scenario: str = "primary") -> RuleExample:
    return RuleExample(
        example_id=example_id,
        title=title,
        scenario=scenario,
        outcome=ExampleOutcome.MATCH if matches else ExampleOutcome.NO_MATCH,
        files=(
            ExampleFile.python(_MANIFEST, _CONFIG),
            ExampleFile.python("app/task_store.py", _STORE.replace("{guard}", guard)),
        ),
        focus_path=PurePosixPath("app/task_store.py"),
        expected_count=1 if matches else 0,
        public=True,
    )


@final
class LifecycleUpdateRequiresStateGuard(Rule):
    id = "lifecycle-update-requires-state-guard"
    code = "SARJ598"
    documentation = RuleDocumentation(
        default_level=Severity.WARNING,
        summary="An UPDATE that sets a configured lifecycle column must constrain that column or a compare-and-set column in its WHERE clause.",
        rationale=(
            "An UPDATE that writes a lifecycle column by key alone lets a redelivered, retried or late writer regress "
            "a finished row, repeating completed work and its side effects. Constraining the current state, or a "
            "column the same UPDATE compares and sets, turns that writer into a no-op."
        ),
        remediation=(
            "Constrain the lifecycle column in WHERE, for example `AND status <> ALL(%s)` for terminal states or "
            "`AND status = %s` for an observed state, or compare a column the UPDATE also sets. Check the affected "
            "row count when the caller needs to know the write was skipped. For an intentional blind overwrite, add "
            "an exact SARJ598 exception explaining why regression is safe."
        ),
        category=RuleCategory.CORRECTNESS,
        autofix=AutofixPolicy.NONE,
        limitations=(
            (
                "Lifecycle columns come only from `lifecycle_columns` entries such as `task.status` in the nearest "
                "`.sarj-standards.toml` table `[python.lifecycle-update-requires-state-guard]`; column names never "
                "establish lifecycle intent, and repositories without that table get no findings. The manifest is read "
                "from the working tree."
            ),
            (
                "Checks recovered UPDATE statements, including data-modifying CTEs, reaching import-proven Psycopg "
                "execution outside tests. The target table is matched by unqualified name. A WHERE conjunct guards "
                "only when every OR branch references the target's lifecycle column or another column the same UPDATE "
                "assigns, outside subqueries; optional guards such as `(%s IS NULL OR status = %s)` do not."
            ),
            (
                "A SET-side CASE that keeps the column by default and changes it only under conditions on that column "
                "is a compare-and-set. A locking SELECT (FOR UPDATE, FOR NO KEY UPDATE, FOR SHARE) of the lifecycle "
                "column on the same relation, in the statement or earlier in the same function, is accepted as a "
                "read-check-write guard; whether Python then checks the value is not proven."
            ),
            (
                "Unresolved SQL in the target, assignments or WHERE clause abstains, as do queries the shared Psycopg "
                "SQL recovery cannot prove. Transition legality is not analyzed."
            ),
        ),
        examples=(
            _example("unguarded-status-update", "A keyed status write can regress a finished row", "", matches=True),
            _example(
                "terminal-state-guard",
                "Exclude terminal states in WHERE",
                " AND status <> ALL(%s)",
                matches=False,
            ),
            _example(
                "optional-state-guard",
                "A guard skipped by a NULL parameter does not constrain state",
                " AND (%s::text IS NULL OR status = %s)",
                matches=True,
                scenario="compare-and-set",
            ),
            _example(
                "compare-and-set-guard",
                "Compare a column the UPDATE also sets",
                " AND updated_at = %s",
                matches=False,
                scenario="compare-and-set",
            ),
        ),
    )
    description = documentation.summary

    @override
    def check_context(self, context: PythonFileContext) -> list[Diagnostic]:
        if (
            context.generated
            or context.tree is None
            or is_test_path(context.path)
            or "UPDATE" not in context.source.upper()
        ):
            return []
        configured = _lifecycle_columns(context.path)
        if not configured:
            return []
        queries = list(store_queries(context))
        findings: dict[ast.expr, Diagnostic] = {}
        for query in queries:
            locked = _locked_reads(query.statement) | {
                column
                for prior in queries
                if prior.method is not None and prior.method is query.method and prior.node.lineno <= query.node.lineno
                for column in _locked_reads(prior.statement)
            }
            for column in _unguarded_lifecycle_writes(query.statement, configured - locked):
                findings.setdefault(
                    query.node,
                    Diagnostic(
                        context.path,
                        query.node.lineno,
                        query.node.col_offset + 1,
                        self.code,
                        f"This UPDATE sets lifecycle column {column} without constraining it, or a column it also "
                        "sets, in WHERE; a late or duplicate writer can regress state. Add a state guard such as "
                        "`AND status <> ALL(%s)`, or explain an intentional overwrite in an exact SARJ598 exception.",
                        severity=Severity.WARNING,
                    ),
                )
        return sorted(findings.values(), key=lambda finding: (finding.line, finding.col))


@dataclass(frozen=True, slots=True)
class _LifecycleColumn:
    relation: str
    column: str


@dataclass(frozen=True, slots=True)
class _UpdateTarget:
    relation: str
    qualifiers: frozenset[str]
    assigned: frozenset[str]
    compared_in_set: frozenset[str]


def _lifecycle_columns(path: Path) -> frozenset[_LifecycleColumn]:
    try:
        for ancestor in list(path.resolve().parents)[:_MAX_ANCESTORS]:
            manifest = ancestor / _MANIFEST
            if manifest.is_file():
                return _manifest_columns(manifest, manifest.stat().st_mtime_ns)
            if (ancestor / ".git").exists():
                return frozenset()
    except OSError:
        return frozenset()
    return frozenset()


@cache
def _manifest_columns(manifest: Path, _modified: int) -> frozenset[_LifecycleColumn]:
    try:
        options: object = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        message = f"{manifest}: cannot read lifecycle column configuration: {error}"
        raise ValueError(message) from error
    for key in ("python", LifecycleUpdateRequiresStateGuard.id):
        options = options.get(key) if _is_table(options) else None
    if options is None:
        return frozenset()
    entries = options.get("lifecycle_columns") if _is_table(options) else None
    message = (
        f"{manifest}: [python.{LifecycleUpdateRequiresStateGuard.id}].lifecycle_columns must list `table.column` names"
    )
    columns: set[_LifecycleColumn] = set()
    for entry in entries if _is_array(entries) else [None]:
        match entry:
            case str() if _COLUMN.fullmatch(entry):
                relation, _, column = entry.lower().partition(".")
                columns.add(_LifecycleColumn(relation, column))
            case _:
                raise ValueError(message)
    return frozenset(columns)


def _is_table(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _unguarded_lifecycle_writes(statement: exp.Expr, configured: frozenset[_LifecycleColumn]) -> list[str]:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- parser types load only for recovered SQL queries.

    writes: list[str] = []
    for update in statement.find_all(exp.Update):
        target = _update_target(update)
        if target is None:
            continue
        lifecycle = sorted(
            column
            for column in target.assigned - target.compared_in_set
            if _LifecycleColumn(target.relation, column) in configured
        )
        if lifecycle and not _has_state_guard(sql_child(update, "where"), target):
            writes.append(f"{target.relation}.{lifecycle[0]}")
    return writes


def _update_target(update: exp.Update) -> _UpdateTarget | None:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- parser types load only for recovered SQL queries.

    assigned: list[exp.Expr] = []
    compared: set[str] = set()
    for assignment in sql_children(update, "expressions"):
        match sql_child(assignment, "this"):
            case exp.Column() as column if isinstance(assignment, exp.EQ):
                assigned.append(column)
                if _keeps_unless_compared(sql_child(assignment, "expression"), column.name.lower()):
                    compared.add(column.name.lower())
            case _:
                return None
    table = sql_child(update, "this")
    names = relation_key(table)
    where = sql_child(update, "where")
    scanned = [*assigned, *([where] if where is not None else [])]
    if (
        table is None
        or names is None
        or any(_HOLE in item.name for node in scanned for item in node.find_all(exp.Identifier))
    ):
        return None
    return _UpdateTarget(
        names[-1].lower(),
        frozenset({names[-1].lower(), table.alias.lower()} - {""}),
        frozenset(column.name.lower() for column in assigned),
        frozenset(compared),
    )


def _keeps_unless_compared(value: exp.Expr | None, name: str) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- parser types load only for recovered SQL queries.

    match value:
        case exp.Case():
            default = sql_child(value, "default")
            conditions = [sql_child(branch, "this") for branch in sql_children(value, "ifs")]
            return (
                isinstance(default, exp.Column)
                and not default.table
                and default.name.lower() == name
                and all(
                    condition is not None
                    and any(column.name.lower() == name for column in condition.find_all(exp.Column))
                    for condition in conditions
                )
            )
        case _:
            return False


def _locked_reads(statement: exp.Expr) -> set[_LifecycleColumn]:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- parser types load only for recovered SQL queries.

    return {
        read
        for select in statement.find_all(exp.Select)
        if sql_children(select, "locks")
        for read in _selected_columns(select)
    }


def _selected_columns(select: exp.Select) -> set[_LifecycleColumn]:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- parser types load only for recovered SQL queries.

    tables = [table for table in select.find_all(exp.Table) if table.find_ancestor(exp.Select) is select]
    reads: set[_LifecycleColumn] = set()
    for table in tables:
        names = relation_key(table)
        if names is None:
            continue
        qualifiers = {names[-1].lower(), table.alias.lower()} - {""}
        reads.update(
            _LifecycleColumn(names[-1].lower(), column.name.lower())
            for column in select.find_all(exp.Column)
            if (not column.table and len(tables) == 1) or column.table.lower() in qualifiers
        )
    return reads


def _has_state_guard(where: exp.Expr | None, target: _UpdateTarget) -> bool:
    condition = sql_child(where, "this") if where is not None else None
    return condition is not None and any(
        all(_references_assigned(branch, where, target) for branch in _flatten(conjunct, "or"))
        for conjunct in _flatten(condition, "and")
    )


def _references_assigned(branch: exp.Expr, where: exp.Expr | None, target: _UpdateTarget) -> bool:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- parser types load only for recovered SQL queries.

    return any(
        column.name.lower() in target.assigned
        and (not column.table or column.table.lower() in target.qualifiers)
        and column.find_ancestor(exp.Select, exp.Where) is where
        for column in branch.find_all(exp.Column)
    )


def _flatten(node: exp.Expr, connector: str) -> list[exp.Expr]:
    from sqlglot import exp  # ruff: ignore[import-outside-top-level] -- parser types load only for recovered SQL queries.

    match node:
        case exp.Paren():
            return _flatten(node.unnest(), connector)
        case exp.And() | exp.Or() if node.key == connector:
            return [
                part
                for child in (sql_child(node, "this"), sql_child(node, "expression"))
                if child is not None
                for part in _flatten(child, connector)
            ]
        case _:
            return [node]
