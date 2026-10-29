from __future__ import annotations

from bisect import bisect_right
from pathlib import PurePosixPath
import re
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
    dollar_quoted_spans,
    is_dump_file,
    is_generated_migration,
    is_postgres_migration,
    mask_sql,
    mask_sql_comments,
    source_location,
    sql_comments,
)
from sarj_sql_lint.rules._constraint_analysis import (
    TableKey,
    Token,
    consume,
    identifier,
    sequence,
    split_actions,
    tokenize,
)
from sarj_sql_lint.rules._copy_input import sql_before_copy_input


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_SECTION = re.compile(r"^\s*(?:migrate:(?:up|down)\b|\+goose\s+(?:up|down)\b|changeset\s+\S+)", re.IGNORECASE)
_NON_NEWLINE = re.compile(r"[^\r\n]")
_NON_PRODUCTION = frozenset({"test", "tests", "testing", "__tests__", "fixtures", "vendor", "node_modules"})
_MAX_RELATION_PARTS = 2
_PLAIN_TYPES = frozenset(
    {
        ("BIGINT",),
        ("BOOLEAN",),
        ("BYTEA",),
        ("DATE",),
        ("DECIMAL",),
        ("DOUBLE", "PRECISION"),
        ("INTEGER",),
        ("INT",),
        ("JSONB",),
        ("NUMERIC",),
        ("REAL",),
        ("SMALLINT",),
        ("TEXT",),
        ("TIMESTAMPTZ",),
        ("TIMESTAMP", "WITH", "TIME", "ZONE"),
        ("UUID",),
    }
)
_SIMPLE_COLUMN_ACTIONS = (
    ("SET", "NOT", "NULL"),
    ("DROP", "NOT", "NULL"),
    ("DROP", "DEFAULT"),
)


class _Statement(NamedTuple):
    tokens: list[Token]
    start: int
    section: int


class _Target(NamedTuple):
    relation: TableKey
    guarded: bool
    only: bool
    descendants: bool


class _Action(NamedTuple):
    family: str
    namespace: str
    name: str


class _Alter(NamedTuple):
    target: _Target
    family: str
    objects: frozenset[tuple[str, str]]


@final
class CombineAlterTable(Rule):
    id = "combine-alter-table"
    code = "SARJ123"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Combine compatible adjacent ALTER TABLE actions.",
        rationale=(
            "Repeating ALTER TABLE for compatible changes to one relation obscures a single schema operation and "
            "adds avoidable statements. PostgreSQL supports comma-separated subcommands, including multiple drops."
        ),
        remediation=(
            "Combine the reported adjacent statements into one ALTER TABLE with comma-separated actions, preserving "
            "their order, guards, table modifiers, and drop behavior. Keep deployment checkpoints and operations "
            "whose ordering, expression evaluation, or lock contracts differ in separate statements."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only authored PostgreSQL migrations are checked; dumps, generator-owned migrations, fixtures, and test sources are excluded.",
            "Only adjacent statements with the same explicitly qualified relation and identical IF EXISTS, ONLY, and descendant modifiers are combined. Any intervening statement or migration-section directive ends the group.",
            "Supported groups contain only DROP COLUMN/DROP CONSTRAINT actions, only nullable additions of recognized built-in scalar types with optional NULL and without defaults or other constraints, or only identical SET NOT NULL, DROP NOT NULL, or DROP DEFAULT actions on distinct columns.",
            "Renames, schema and partition changes, type conversions, expressions, defaults, constraint additions/validation, repeated object targets, unsupported types, and malformed syntax remain separate. No catalog or search_path equivalence is inferred.",
            "Analysis stops at an executable COPY FROM STDIN command because raw data framing is unsupported; later statements are not checked.",
            "No automatic rewrite moves comments or changes migration behavior. Existing DDL event triggers may observe statement boundaries; an intentional boundary needs an exact, explained rule exception.",
        ),
        examples=(
            RuleExample(
                example_id="combine-related-drops",
                title="Drop a legacy foreign key and its column together",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_retire_version.sql",
                        "ALTER TABLE call DROP CONSTRAINT IF EXISTS call_scenario_version_fkey;\n"
                        "ALTER TABLE call DROP COLUMN IF EXISTS scenario_version_id;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_retire_version.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="combined-drops",
                title="One statement retains the drop order and guards",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_retire_version.sql",
                        "ALTER TABLE call\n"
                        "    DROP CONSTRAINT IF EXISTS call_scenario_version_fkey,\n"
                        "    DROP COLUMN IF EXISTS scenario_version_id;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_retire_version.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        source = sql_before_copy_input(source)
        if (
            {part.casefold() for part in path.parts} & _NON_PRODUCTION
            or is_dump_file(source, path)
            or is_generated_migration(path, source)
            or not is_postgres_migration(path, source)
        ):
            return []
        findings: list[Diagnostic] = []
        previous: _Alter | None = None
        previous_section = -1
        first_line = 0
        for statement in _statements(source):
            altered = _compatible_alter(statement.tokens)
            joins_previous = (
                altered is not None
                and previous is not None
                and statement.section == previous_section
                and altered.target == previous.target
                and altered.family == previous.family
                and altered.objects.isdisjoint(previous.objects)
            )
            location = source_location(source, statement.start + (statement.tokens[0].start if statement.tokens else 0))
            if joins_previous and altered is not None and previous is not None:
                findings.append(
                    Diagnostic(
                        path,
                        location.line,
                        location.column,
                        self.code,
                        f"Combine these compatible actions with the ALTER TABLE at line {first_line}; "
                        "use comma-separated subcommands and preserve their order, guards, and drop behavior.",
                    )
                )
                previous = altered._replace(objects=previous.objects | altered.objects)
            else:
                previous = altered
                first_line = location.line
            previous_section = statement.section
        return findings


def _statements(source: str) -> Iterator[_Statement]:
    masked_chars = list(mask_sql(source, mask_dollar_literals=True))
    for start, end in dollar_quoted_spans(source):
        masked_chars[start:end] = _NON_NEWLINE.sub(" ", source[start:end])
    masked = "".join(masked_chars)
    view = mask_sql_comments(source)
    sections = [
        comment.line
        for comment in sql_comments(source, mask_dollar_literals=True)
        if not comment.block and _SECTION.match(comment.body)
    ]
    start = 0
    for end in (*[match.start() for match in re.finditer(r";", masked)], len(source)):
        text = view[start:end]
        tokens = tokenize(text)
        if tokens:
            line = source_location(source, start + tokens[0].start).line
            yield _Statement(tokens, start, bisect_right(sections, line))
        elif text.strip():
            yield _Statement([], start, -1)
        start = end + 1


def _compatible_alter(tokens: list[Token]) -> _Alter | None:
    if not sequence(tokens, 0, ("ALTER", "TABLE")):
        return None
    cursor = 2
    guarded = sequence(tokens, cursor, ("IF", "EXISTS"))
    cursor += 2 if guarded else 0
    only = consume(tokens, cursor, "ONLY")
    cursor += 1 if only else 0
    parsed = identifier(tokens, cursor)
    if parsed is None or len(parsed[0]) > _MAX_RELATION_PARTS or not all(parsed[0]):
        return None
    relation, cursor = parsed
    descendants = cursor < len(tokens) and tokens[cursor].text == "*"
    cursor += 1 if descendants else 0
    if only and descendants:
        return None
    segments = split_actions(tokens[cursor:])
    if segments is None:
        return None
    actions = [_action(segment) for segment in segments]
    if any(action is None for action in actions):
        return None
    recognized = [action for action in actions if action is not None]
    family = recognized[0].family
    objects = frozenset((action.namespace, action.name) for action in recognized)
    if len(objects) != len(recognized) or any(action.family != family for action in recognized):
        return None
    return _Alter(_Target(relation, guarded, only, descendants), family, objects)


def _action(tokens: list[Token]) -> _Action | None:
    if consume(tokens, 0, "DROP"):
        return _drop_action(tokens)
    if consume(tokens, 0, "ADD"):
        return _add_action(tokens)
    if not consume(tokens, 0, "ALTER"):
        return None
    cursor = 2 if consume(tokens, 1, "COLUMN") else 1
    parsed = identifier(tokens, cursor)
    if parsed is None or len(parsed[0]) != 1 or not all(parsed[0]):
        return None
    name, cursor = parsed
    for operation in _SIMPLE_COLUMN_ACTIONS:
        if len(tokens) == cursor + len(operation) and sequence(tokens, cursor, operation):
            return _Action(" ".join(operation), "column", name[0])
    return None


def _drop_action(tokens: list[Token]) -> _Action | None:
    namespace = "constraint" if consume(tokens, 1, "CONSTRAINT") else "column"
    cursor = 2 if namespace == "constraint" or consume(tokens, 1, "COLUMN") else 1
    if sequence(tokens, cursor, ("IF", "EXISTS")):
        cursor += 2
    parsed = identifier(tokens, cursor)
    if parsed is None or len(parsed[0]) != 1 or not all(parsed[0]):
        return None
    name, cursor = parsed
    if cursor < len(tokens) and (consume(tokens, cursor, "CASCADE") or consume(tokens, cursor, "RESTRICT")):
        cursor += 1
    return _Action("drop", namespace, name[0]) if cursor == len(tokens) else None


def _add_action(tokens: list[Token]) -> _Action | None:
    cursor = 2 if consume(tokens, 1, "COLUMN") else 1
    if sequence(tokens, cursor, ("IF", "NOT", "EXISTS")):
        cursor += 3
    parsed = identifier(tokens, cursor)
    if parsed is None or len(parsed[0]) != 1 or not all(parsed[0]):
        return None
    name, cursor = parsed
    type_tokens = tokens[cursor:]
    if type_tokens and consume(type_tokens, len(type_tokens) - 1, "NULL"):
        type_tokens = type_tokens[:-1]
    if (
        any(token.quoted for token in type_tokens)
        or tuple(token.text.upper() for token in type_tokens) not in _PLAIN_TYPES
    ):
        return None
    return _Action("add-nullable-column", "column", name[0])
