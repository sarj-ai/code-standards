from __future__ import annotations

from collections import Counter
from itertools import product
from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, final, override

from sqlglot import exp

from sarj_sql_lint.rule_base import (
    AutofixPolicy,
    DefaultLevel,
    Diagnostic,
    ExampleFile,
    ExampleOutcome,
    Rule,
    RuleCategory,
    RuleDocumentation,
    RuleExample,
    is_dump_file,
    is_generated_migration,
    is_postgres_migration,
    source_location,
)
from sarj_sql_lint.rules._column_contracts import child, column_key, column_offset, table_contracts, unparenthesize


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sarj_sql_lint.rules._column_contracts import TableContract


_BOOLEAN = re.compile(r"\bBOOL(?:EAN)?\b", re.IGNORECASE)
_MAX_FLAGS = 6
_MIN_FLAGS = 2


@final
class PreferConstrainedStatus(Rule):
    id = "prefer-constrained-status"
    code = "SARJ129"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Review CHECK-constrained boolean states for a single status column.",
        rationale=(
            "A CHECK that rules out combinations of multiple required booleans exposes a shared state contract. "
            "A constrained status column can represent the permitted states explicitly and avoid invalid flag combinations."
        ),
        remediation=(
            "Review whether these dependent booleans represent one lifecycle. If so, replace them with one status "
            "column and a CHECK over its allowed values, preserving every valid state and application transition."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Advisory only: SQL proves dependence, not that flags are semantically one lifecycle. Independent boolean names alone never produce findings.",
            "Checks only authored PostgreSQL migration CREATE TABLE definitions with two to six NOT NULL BOOLEAN columns participating in a pure boolean CHECK. Nullable flags, unknown expressions, functions, generated columns, dumps and generated migrations are excluded.",
            "Truth tables cover AND, OR, NOT, boolean equality/inequality and IS TRUE/FALSE. Flags referenced by multiple CHECKs are excluded because interactions may eliminate dependence. Tautologies, contradictions and checks equivalent to independent single-column restrictions are excluded. No automatic schema rewrite is offered.",
        ),
        examples=(
            RuleExample(
                example_id="dependent-lifecycle-flags",
                title="A CHECK makes two required flags dependent",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_job.sql",
                        "CREATE TABLE job (requested BOOLEAN NOT NULL, confirmed BOOLEAN NOT NULL, CHECK (NOT confirmed OR requested));\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_job.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="independent-flags",
                title="Unrelated flags retain their independent values",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_job.sql",
                        "CREATE TABLE job (enabled BOOLEAN NOT NULL, archived BOOLEAN NOT NULL);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_job.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            _BOOLEAN.search(source) is None
            or not is_postgres_migration(path, source)
            or is_dump_file(source, path)
            or is_generated_migration(path, source)
        ):
            return []
        findings: list[Diagnostic] = []
        for table in table_contracts(source):
            for column, names in _status_candidates(table):
                location = source_location(source, table.offset + column_offset(column))
                findings.append(
                    Diagnostic(
                        path,
                        location.line,
                        location.column,
                        self.code,
                        f"CHECK restricts combinations of required booleans {', '.join(sorted(names))}. "
                        "Review one constrained status column for this shared state contract; preserve every valid state.",
                        DefaultLevel.WARNING,
                    )
                )
        return findings


def _status_candidates(table: TableContract) -> Iterator[tuple[exp.ColumnDef, frozenset[str]]]:
    flags = {column_key(column): column for column in table.columns if _required_boolean(column)}
    referenced = [frozenset(column_key(column) for column in check.find_all(exp.Column)) for check in table.checks]
    counts = Counter(name for names in referenced for name in names)
    for check, names in zip(table.checks, referenced, strict=True):
        if not names <= flags.keys() or any(counts[name] > 1 for name in names):
            continue
        if _dependent(check, names):
            column = min((flags[name] for name in names), key=column_offset)
            yield column, names


def _required_boolean(column: exp.ColumnDef) -> bool:
    return (
        isinstance(column.kind, exp.DataType)
        and column.kind.is_type(exp.DataType.Type.BOOLEAN)
        and any(
            isinstance(item.kind, exp.NotNullColumnConstraint) and item.kind.args.get("allow_null") is not True
            for item in column.constraints
        )
        and not any(isinstance(item.kind, exp.ComputedColumnConstraint) for item in column.constraints)
    )


def _dependent(check: exp.Expr, names: frozenset[str]) -> bool:
    if not _MIN_FLAGS <= len(names) <= _MAX_FLAGS:
        return False
    ordered = sorted(names)
    accepted: list[tuple[bool, ...]] = []
    for values in product((False, True), repeat=len(ordered)):
        result = _boolean_value(check, dict(zip(ordered, values, strict=True)))
        if result is None:
            return False
        if result:
            accepted.append(values)
    if not accepted:
        return False
    independent_count = 1
    for index in range(len(ordered)):
        independent_count *= len({values[index] for values in accepted})
    return len(accepted) < independent_count


def _boolean_value(node: exp.Expr | None, values: dict[str, bool]) -> bool | None:
    if node is None:
        return None
    node = unparenthesize(node)
    if isinstance(node, exp.Boolean):
        return node.sql(comments=False).upper() == "TRUE"
    if isinstance(node, exp.Column):
        return None if node.table else values.get(column_key(node))
    if isinstance(node, exp.Not):
        value = _boolean_value(child(node, "this"), values)
        return None if value is None else not value
    if isinstance(node, exp.And | exp.Or | exp.EQ | exp.NEQ | exp.Is):
        left = _boolean_value(child(node, "this"), values)
        right = _boolean_value(child(node, "expression"), values)
        if left is None or right is None:
            return None
        if isinstance(node, exp.And):
            return left and right
        if isinstance(node, exp.Or):
            return left or right
        return left != right if isinstance(node, exp.NEQ) else left == right
    return None
