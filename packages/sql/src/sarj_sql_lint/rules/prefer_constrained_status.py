from __future__ import annotations

from itertools import chain, combinations, islice, product
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
_MAX_CHECKS = 32
_MAX_PREDICATE_NODES = 512


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
            "Review whether these dependent booleans represent one lifecycle. Retain an authoritative Boolean "
            "when one bit determines the rest; use one constrained status for a multiway lifecycle. "
            "Preserve every valid combination, independent field, external contract and application transition."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Advisory only: SQL proves dependence, not that flags are semantically one lifecycle. Independent boolean names alone never produce findings.",
            "Checks only authored PostgreSQL migration CREATE TABLE definitions with two to six NOT NULL BOOLEAN columns in each connected CHECK group. Nullable flags, unknown expressions, functions and generated columns exclude their group; duplicate columns, empty delimited identifiers, dumps and generated migrations are excluded.",
            "Truth tables conjoin every CHECK sharing a participating column, covering AND, OR, NOT, boolean equality/inequality and IS TRUE/FALSE. Constant false CHECKs and opaque column-free CHECKs exclude the table. Tautologies, contradictions and restrictions equivalent to independent fields are excluded.",
            "Only irreducible dependent factors are reported. Independent flags and separate dependent groups remain separate even when a tautological expression connects them syntactically. Every accepted combination must survive a reviewed migration; the analysis does not prove a lifecycle or whole-table reachability.",
            "Tables exceeding 32 CHECKs or 512 CHECK expression nodes abstain. Connected groups exceeding six referenced columns abstain. No automatic schema rewrite is offered; DML, later ALTER statements, defaults, serialized interfaces and transition ordering require review.",
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
                example_id="joint-lifecycle-constraints",
                scenario="joint-lifecycle",
                title="Multiple CHECKs jointly restrict three lifecycle observations",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_job.sql",
                        "CREATE TABLE job (requested BOOLEAN NOT NULL, confirmed BOOLEAN NOT NULL, archived BOOLEAN NOT NULL, "
                        "CHECK (NOT confirmed OR requested), CHECK (NOT archived OR confirmed));\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_job.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-joint-status-domain",
                scenario="joint-lifecycle",
                title="A reviewed status preserves all four outcomes allowed by the implication chain",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_job.sql",
                        "CREATE TABLE job (status TEXT NOT NULL CHECK (status IN ('new', 'requested', 'confirmed', 'archived')));\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_job.sql"),
                expected_count=0,
                public=True,
            ),
            RuleExample(
                example_id="independent-axis-is-preserved",
                scenario="independent-axis",
                title="A tautological flag does not join the dependent lifecycle factor",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_job.sql",
                        "CREATE TABLE job (requested BOOLEAN NOT NULL, confirmed BOOLEAN NOT NULL, muted BOOLEAN NOT NULL, "
                        "CHECK ((NOT confirmed OR requested) AND (muted OR NOT muted)));\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_job.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="explicit-status-preserves-independent-flag",
                scenario="independent-axis",
                title="A reviewed status models three outcomes while muted remains independent",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_job.sql",
                        "CREATE TABLE job (status TEXT NOT NULL CHECK (status IN ('new', 'requested', 'confirmed')), "
                        "muted BOOLEAN NOT NULL);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_job.sql"),
                expected_count=0,
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
    candidates: list[tuple[exp.ColumnDef, frozenset[str]]] = []
    for names, guards in _check_components(table):
        if len(names) > _MAX_FLAGS or not names <= flags.keys():
            continue
        ordered = tuple(sorted(names))
        accepted = _accepted_states(guards, ordered)
        if accepted == frozenset():
            return
        if accepted is None:
            continue
        for factor in _dependent_factors(accepted, ordered):
            column = min((flags[name] for name in factor), key=column_offset)
            candidates.append((column, factor))
    yield from sorted(candidates, key=lambda candidate: column_offset(candidate[0]))


def _check_components(table: TableContract) -> Iterator[tuple[frozenset[str], tuple[exp.Expr, ...]]]:
    columns = table.columns
    if len({column_key(column) for column in columns}) != len(columns) or any(
        not identifier.name for identifier in table.schema.find_all(exp.Identifier)
    ):
        return
    checks = table.checks
    nodes = chain.from_iterable(check.walk() for check in checks)
    if len(checks) > _MAX_CHECKS or sum(1 for _ in islice(nodes, _MAX_PREDICATE_NODES + 1)) > _MAX_PREDICATE_NODES:
        return
    referenced = [frozenset(column_key(column) for column in check.find_all(exp.Column)) for check in checks]
    if any(
        not names and _boolean_value(check, {}) is not True for check, names in zip(checks, referenced, strict=True)
    ):
        return
    yield from _connected_checks(checks, referenced)


def _connected_checks(
    checks: tuple[exp.Expr, ...], referenced: list[frozenset[str]]
) -> Iterator[tuple[frozenset[str], tuple[exp.Expr, ...]]]:
    pending = [(names, (check,)) for check, names in zip(checks, referenced, strict=True) if names]
    while pending:
        names, guards = pending.pop(0)
        while True:
            for index, (other, related) in enumerate(pending):
                if names & other:
                    names |= other
                    guards += related
                    pending.pop(index)
                    break
            else:
                yield names, guards
                break


def _accepted_states(checks: tuple[exp.Expr, ...], names: tuple[str, ...]) -> frozenset[tuple[bool, ...]] | None:
    accepted: set[tuple[bool, ...]] = set()
    for values in product((False, True), repeat=len(names)):
        bindings = dict(zip(names, values, strict=True))
        outcomes = tuple(_boolean_value(check, bindings) for check in checks)
        if any(outcome is None for outcome in outcomes):
            return None
        if all(outcomes):
            accepted.add(values)
    return frozenset(accepted)


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


def _dependent_factors(accepted: frozenset[tuple[bool, ...]], names: tuple[str, ...]) -> Iterator[frozenset[str]]:
    if len(names) < _MIN_FLAGS:
        return
    for left, right in _bipartitions(len(names)):
        left_states = _project(accepted, left)
        right_states = _project(accepted, right)
        if len(accepted) == len(left_states) * len(right_states):
            yield from _dependent_factors(left_states, tuple(names[index] for index in left))
            yield from _dependent_factors(right_states, tuple(names[index] for index in right))
            return
    yield frozenset(names)


def _bipartitions(width: int) -> Iterator[tuple[tuple[int, ...], tuple[int, ...]]]:
    for size in range(1, width):
        for tail in combinations(range(1, width), size - 1):
            left = (0, *tail)
            yield left, tuple(index for index in range(width) if index not in left)


def _project(states: frozenset[tuple[bool, ...]], indices: tuple[int, ...]) -> frozenset[tuple[bool, ...]]:
    return frozenset(tuple(state[index] for index in indices) for state in states)


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
