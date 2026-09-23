from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NamedTuple, final, override

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
)
from sarj_sql_lint.rules._index_analysis import (
    IndexDefinition,
    IndexDrop,
    IndexSignature,
    authored_index_operations,
    drop_namespace_keys,
    index_namespace_key,
)


if TYPE_CHECKING:
    from pathlib import Path


@final
class NoDuplicateIndex(Rule):
    id = "no-duplicate-index"
    code = "SARJ117"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.WARNING,
        summary="Report duplicate and conservatively covered indexes that remain active in one authored migration.",
        rationale=(
            "Duplicate definitions, non-unique copies of unique access paths, and strict B-tree prefixes can add "
            "write amplification, storage, vacuum work, and planner choices without a distinct measured read path."
        ),
        remediation=(
            "Remove the repeated definition or verify the exact query plan before retaining a potentially covered "
            "index. Preserve an index when uniqueness, key order, operator class, collation, predicate, included "
            "columns, partition scope, access method, tablespace, or storage parameters give it distinct behavior."
        ),
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only explicit indexes in one authored production migration are checked; tests, dumps, fixtures, recognized generator-owned migrations, and indexes that exist only outside the file are excluded.",
            "DROP INDEX operations in the same migration remove the named definition from the final active set before repeated definitions are compared.",
            "The normalized definition includes uniqueness, table and ONLY scope, access method, ordered key expressions and operator classes, INCLUDE columns, NULLS DISTINCT treatment, storage parameters, tablespace, and WHERE predicate.",
            "Semantically equivalent expressions with different normalized source spelling are intentionally not inferred.",
            "Left-prefix review is limited to ordinary non-unique B-tree indexes with identical physical options and compatible INCLUDE coverage.",
        ),
        examples=(
            RuleExample(
                example_id="duplicate-index-shape",
                title="Two active indexes repeat the same normalized definition",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/002_indexes.sql",
                        "CREATE INDEX event_owner_a ON event(owner_id DESC);\n"
                        "CREATE INDEX event_owner_b ON event ( owner_id DESC );\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/002_indexes.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="distinct-index-predicates",
                title="Different partial-index predicates remain distinct",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "migrations/002_indexes.sql",
                        "CREATE INDEX event_open ON event(owner_id) WHERE status = 'open';\n"
                        "CREATE INDEX event_closed ON event(owner_id) WHERE status = 'closed';\n",
                    ),
                ),
                focus_path=PurePosixPath("migrations/002_indexes.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        indexes = _active_indexes(path, source)
        findings: list[Diagnostic] = []
        reported: set[int] = set()
        seen: dict[IndexSignature, IndexDefinition] = {}
        for index in indexes:
            first = seen.setdefault(index.signature, index)
            if first is index:
                continue
            reported.add(index.start)
            findings.append(
                Diagnostic(
                    path,
                    index.line,
                    index.column,
                    self.code,
                    f"Index `{index.name}` duplicates `{first.name}` on table `{index.table}`; remove the later index.",
                )
            )
        _find_repeated_access_paths(indexes, reported, findings, path, self.code)
        for position, later in enumerate(indexes):
            if later.start in reported:
                continue
            earlier = next(
                (
                    candidate
                    for candidate in indexes[:position]
                    if candidate.start not in reported
                    and (_strict_prefix_pair(candidate, later) or _strict_prefix_pair(later, candidate))
                ),
                None,
            )
            if earlier is None:
                continue
            shorter, longer = (earlier, later) if _strict_prefix_pair(earlier, later) else (later, earlier)
            reported.add(later.start)
            findings.append(
                Diagnostic(
                    path,
                    later.line,
                    later.column,
                    self.code,
                    f"Index `{shorter.name}` is a strict left prefix of `{longer.name}` on table `{later.table}`; "
                    "the pair may overlap, so verify the exact query plan before retaining both.",
                )
            )
        findings.sort(key=lambda diagnostic: (diagnostic.line, diagnostic.col))
        return findings


class _IndexAccessSignature(NamedTuple):
    only: bool
    table: str
    method: str
    keys: tuple[str, ...]
    include: tuple[str, ...]
    storage_parameters: tuple[str, ...]
    tablespace: str
    predicate: str


def index_access_signature(index: IndexDefinition) -> _IndexAccessSignature:
    return _IndexAccessSignature(
        index.only,
        index.table,
        index.method,
        index.keys,
        index.include,
        index.storage_parameters,
        index.tablespace,
        index.predicate,
    )


def _strict_prefix_pair(shorter: IndexDefinition, longer: IndexDefinition) -> bool:
    if shorter.unique or longer.unique or shorter.method != "btree" or longer.method != "btree":
        return False
    if (
        _prefix_context(shorter) != _prefix_context(longer)
        or not shorter.keys
        or len(shorter.keys) >= len(longer.keys)
        or longer.keys[: len(shorter.keys)] != shorter.keys
    ):
        return False
    available = frozenset((*longer.keys, *longer.include))
    return all(column in available for column in shorter.include)


@dataclass(frozen=True, slots=True)
class _IndexContext:
    table: str
    only: bool
    predicate: str
    storage_parameters: tuple[str, ...]
    tablespace: str


def _prefix_context(index: IndexDefinition) -> _IndexContext:
    return _IndexContext(
        table=index.table,
        only=index.only,
        predicate=index.predicate,
        storage_parameters=index.storage_parameters,
        tablespace=index.tablespace,
    )


def _active_indexes(path: Path, source: str) -> list[IndexDefinition]:
    active: dict[str, IndexDefinition] = {}
    for operation in authored_index_operations(path, source):
        if isinstance(operation, IndexDrop):
            dropped = drop_namespace_keys(operation, set(active))
            active = {key: index for key, index in active.items() if key not in dropped}
            continue
        index = operation
        key = index_namespace_key(index) or f"<unnamed>@{index.start}"
        active.setdefault(key, index)
    return sorted(active.values(), key=lambda definition: definition.start)


def _find_repeated_access_paths(
    indexes: list[IndexDefinition], reported: set[int], findings: list[Diagnostic], path: Path, code: str
) -> None:
    for position, index in enumerate(indexes):
        if index.start in reported:
            continue
        counterpart = next(
            (
                candidate
                for candidate in indexes[:position]
                if candidate.start not in reported
                and candidate.unique != index.unique
                and index_access_signature(candidate) == index_access_signature(index)
            ),
            None,
        )
        if counterpart is None:
            continue
        nonunique, unique = (counterpart, index) if index.unique else (index, counterpart)
        reported.add(index.start)
        findings.append(
            Diagnostic(
                path,
                index.line,
                index.column,
                code,
                f"Non-unique index `{nonunique.name}` repeats unique access path `{unique.name}` on table "
                f"`{index.table}`; remove the non-unique copy unless an exact query plan proves distinct value.",
            )
        )
