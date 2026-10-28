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
    mask_sql_literals_and_comments,
    source_location,
)
from sarj_sql_lint.rules._constraint_analysis import (
    TableKey,
    Token,
    consume,
    fresh_create_table,
    identifier,
    is_identifier_token,
    is_validating_add_action,
    matching_paren,
    migration_section_lines,
    sequence,
    split_actions,
    table_actions,
    tokenize,
    top_level_tokens,
)


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


_NON_NEWLINE = re.compile(r"[^\r\n]")
_NON_PRODUCTION = frozenset({"test", "tests", "testing", "__tests__", "fixtures", "vendor", "node_modules"})
_MAX_RELATION_PARTS = 2


class _Statement(NamedTuple):
    tokens: list[Token]
    start: int
    section: int


class _FreshTable(NamedTuple):
    columns: frozenset[str]
    start: int


class _Definition(NamedTuple):
    start: int
    columns: frozenset[str] | None


class _UniqueIndex(NamedTuple):
    name: TableKey
    table: TableKey
    columns: frozenset[str]


class _IndexConsumers(NamedTuple):
    exact: dict[TableKey, int]
    by_name: dict[str, int]


@final
class NewTableInlineConstraints(Rule):
    id = "new-table-inline-constraints"
    code = "SARJ121"
    documentation = RuleDocumentation(
        default_level=DefaultLevel.ERROR,
        summary="Declare new-table constraints inside CREATE TABLE.",
        rationale=(
            "Splitting an empty table's primary key, uniqueness, foreign keys, and checks into later statements "
            "hides its complete integrity contract and adds avoidable ALTER TABLE operations."
        ),
        remediation=(
            "Move these constraints into the original CREATE TABLE, preserving their names and options. "
            "A plain unique column index can use a named UNIQUE constraint. Keep ordinary, partial, expression, "
            "and concurrent indexes separate; PostgreSQL cannot express those as equivalent table constraints."
        ),
        category=RuleCategory.MAINTAINABILITY,
        autofix=AutofixPolicy.NONE,
        limitations=(
            "Only authored PostgreSQL migrations and unconditional empty CREATE TABLE definitions are checked. Conditional creation, dumps, generated migrations, fixtures, LIKE, inheritance, and partition definitions are excluded.",
            "Unknown SQL, data statements, transaction or migration-section boundaries, and alterations other than inline constraint candidates revoke the empty-table proof. NOT VALID, NOT ENFORCED, and USING INDEX contracts remain separate.",
            "Foreign keys remain separate when their referenced table or matching unique key is declared after the child definition in the same section; cyclic table dependencies are not reordered. Unknown key expressions retain conservative ordering checks.",
            "Only plain unique indexes over original columns without guards, ordering, expressions, predicates, concurrency, or physical options are candidates for an inline UNIQUE constraint. Later named index attachment, alteration, or removal preserves the standalone index contract, including Down sections. No automatic rewrite changes catalog objects or migration behavior.",
            "Relation matching preserves explicit schemas and quoted identifier case; search_path, catalog-qualified foreign-key targets, and unsupported unquoted identifier spellings are not inferred.",
        ),
        examples=(
            RuleExample(
                example_id="separate-new-table-primary-key",
                title="The new table's primary key belongs in its definition",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_invite.sql",
                        "CREATE TABLE invite (id UUID, email TEXT);\n"
                        "ALTER TABLE invite ADD CONSTRAINT invite_pkey PRIMARY KEY (id);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_invite.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="inline-constraints-and-partial-index",
                title="Inline constraints and a separate partial expression index",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_invite.sql",
                        "CREATE TABLE invite (id UUID PRIMARY KEY, email TEXT, accepted_at TIMESTAMPTZ);\n"
                        "CREATE UNIQUE INDEX invite_open_email ON invite (LOWER(email)) WHERE accepted_at IS NULL;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_invite.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            {part.casefold() for part in path.parts} & _NON_PRODUCTION
            or is_dump_file(source, path)
            or is_generated_migration(path, source)
            or not is_postgres_migration(path, source)
        ):
            return []
        statements = tuple(_statements(source))
        definitions = _definition_positions(statements)
        consumers = _index_consumers(statements)
        fresh: dict[TableKey, _FreshTable] = {}
        findings: list[Diagnostic] = []
        previous_section = -1
        for statement in statements:
            if statement.section != previous_section:
                fresh.clear()
                previous_section = statement.section
            if _track_creation(statement, fresh):
                continue
            if _has_inline_candidate(statement, fresh, definitions, consumers):
                location = source_location(source, statement.start + statement.tokens[0].start)
                findings.append(
                    Diagnostic(
                        path,
                        location.line,
                        location.column,
                        self.code,
                        "Declare this new table's constraints inside its `CREATE TABLE`; preserve constraint names "
                        "and options. Keep ordinary, partial, expression, and concurrent indexes separate.",
                    )
                )
            elif not _preserves_fresh_tables(statement.tokens):
                fresh.clear()
        return findings


def _statements(source: str) -> Iterator[_Statement]:
    masked = mask_sql_literals_and_comments(source, mask_dollar_literals=True)
    for start, end in dollar_quoted_spans(source):
        masked = masked[:start] + _NON_NEWLINE.sub(" ", masked[start:end]) + masked[end:]
    sections = migration_section_lines(source)
    start = 0
    for end in (*[match.start() for match in re.finditer(r";", mask_sql(masked))], len(masked)):
        text = masked[start:end]
        tokens = tokenize(text)
        if tokens:
            line = source_location(source, start + tokens[0].start).line
            yield _Statement(tokens, start, bisect_right(sections, line))
        elif text.strip():
            yield _Statement([], start, -1)
        start = end + 1


def _create_target(tokens: list[Token]) -> tuple[TableKey, int] | None:
    if not consume(tokens, 0, "CREATE"):
        return None
    cursor = 1
    if consume(tokens, cursor, "GLOBAL") or consume(tokens, cursor, "LOCAL"):
        cursor += 1
    if any(consume(tokens, cursor, keyword) for keyword in ("TEMP", "TEMPORARY", "UNLOGGED")):
        cursor += 1
    if not consume(tokens, cursor, "TABLE"):
        return None
    cursor += 1
    if sequence(tokens, cursor, ("IF", "NOT", "EXISTS")):
        cursor += 3
    return identifier(tokens, cursor)


def _definition_positions(statements: tuple[_Statement, ...]) -> dict[tuple[int, TableKey], tuple[_Definition, ...]]:
    definitions: dict[tuple[int, TableKey], tuple[_Definition, ...]] = {}
    for statement in statements:
        if (table := _definition_target(statement.tokens)) is not None:
            key = (statement.section, table)
            definitions[key] = (
                *definitions.get(key, ()),
                _Definition(statement.start, _defined_key_columns(statement.tokens)),
            )
    return definitions


def _defined_key_columns(tokens: list[Token]) -> frozenset[str] | None:
    if (indexed := _plain_unique_index(tokens)) is not None:
        return indexed.columns
    altered = table_actions(tokens)
    if altered is None or len(altered[1]) != 1:
        return None
    action = altered[1][0]
    cursor = 3 if consume(action, 1, "CONSTRAINT") else 1
    if sequence(action, cursor, ("PRIMARY", "KEY")):
        cursor += 2
    elif consume(action, cursor, "UNIQUE"):
        cursor = _after_unique_nulls(action, cursor + 1)
    else:
        return None
    columns = _column_list(action, cursor)
    return columns[0] if columns is not None else None


def _definition_target(tokens: list[Token]) -> TableKey | None:
    if (parsed := _create_target(tokens)) is not None:
        return parsed[0]
    if sequence(tokens, 0, ("CREATE", "UNIQUE", "INDEX")):
        on = next((index for index in range(3, len(tokens)) if consume(tokens, index, "ON")), None)
        if on is None:
            return None
        cursor = on + 1
        if consume(tokens, cursor, "ONLY"):
            cursor += 1
        indexed = identifier(tokens, cursor)
        return indexed[0] if indexed is not None else None
    altered = table_actions(tokens)
    if altered is None:
        return None
    table, actions = altered
    return table if any(_adds_unique_key(action) for action in actions) else None


def _adds_unique_key(action: list[Token]) -> bool:
    if not consume(action, 0, "ADD"):
        return False
    cursor = 3 if consume(action, 1, "CONSTRAINT") else 1
    return sequence(action, cursor, ("PRIMARY", "KEY")) or consume(action, cursor, "UNIQUE")


def _track_creation(statement: _Statement, fresh: dict[TableKey, _FreshTable]) -> bool:
    tokens = statement.tokens
    table = fresh_create_table(tokens)
    parsed = _create_target(tokens)
    if table is None or parsed is None:
        return False
    _, opening = parsed
    closing = matching_paren(tokens, opening)
    if closing is None or closing != len(tokens) - 1:
        return False
    segments = split_actions(tokens[opening + 1 : closing])
    if segments is None or any(consume(segment, 0, "LIKE") for segment in segments):
        return False
    columns = frozenset(
        parsed_column[0][0]
        for segment in segments
        if not any(
            consume(segment, 0, word) for word in ("CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "EXCLUDE")
        )
        and (parsed_column := identifier(segment, 0)) is not None
        and len(parsed_column[0]) == 1
    )
    fresh[table] = _FreshTable(columns, statement.start)
    return True


def _has_inline_candidate(
    statement: _Statement,
    fresh: dict[TableKey, _FreshTable],
    definitions: dict[tuple[int, TableKey], tuple[_Definition, ...]],
    consumers: _IndexConsumers,
) -> bool:
    tokens = statement.tokens
    if (parsed := table_actions(tokens)) is not None:
        table, actions = parsed
        origin = fresh.get(table)
        return origin is not None and all(
            _inline_action(action, origin, statement.section, definitions) for action in actions
        )
    indexed = _plain_unique_index(tokens)
    return (
        indexed is not None
        and indexed.table in fresh
        and indexed.columns <= fresh[indexed.table].columns
        and not _has_later_index_consumer(indexed, statement.start, consumers)
    )


def _inline_action(
    action: list[Token],
    origin: _FreshTable,
    section: int,
    definitions: dict[tuple[int, TableKey], tuple[_Definition, ...]],
) -> bool:
    if not consume(action, 0, "ADD"):
        return False
    top = top_level_tokens(action)
    if any(
        sequence(top, index, pair)
        for index in range(len(top))
        for pair in (("NOT", "VALID"), ("NOT", "ENFORCED"), ("USING", "INDEX"))
    ):
        return False
    cursor = 1
    if consume(action, cursor, "CONSTRAINT"):
        name = identifier(action, cursor + 1)
        if name is None or len(name[0]) != 1:
            return False
        cursor = name[1]
    if sequence(action, cursor, ("FOREIGN", "KEY")):
        return _inline_foreign_key(action, cursor, origin, section=section, definitions=definitions)
    if consume(action, cursor, "CHECK"):
        return is_validating_add_action(action)
    if sequence(action, cursor, ("PRIMARY", "KEY")):
        cursor += 2
    elif consume(action, cursor, "UNIQUE"):
        cursor = _after_unique_nulls(action, cursor + 1)
    else:
        return False
    columns = _column_list(action, cursor)
    return columns is not None and columns[0] <= origin.columns


def _inline_foreign_key(
    action: list[Token],
    cursor: int,
    origin: _FreshTable,
    *,
    section: int,
    definitions: dict[tuple[int, TableKey], tuple[_Definition, ...]],
) -> bool:
    columns = _column_list(action, cursor + 2)
    if columns is None or not columns[0] <= origin.columns:
        return False
    reference = next((index for index in range(cursor, len(action)) if consume(action, index, "REFERENCES")), None)
    parsed_reference = identifier(action, reference + 1) if reference is not None else None
    if parsed_reference is None or not is_validating_add_action(action):
        return False
    target, end = parsed_reference
    referenced_columns = _column_list(action, end)
    return len(target) <= _MAX_RELATION_PARTS and _reference_precedes_origin(
        target, origin, section, definitions, referenced_columns[0] if referenced_columns is not None else None
    )


def _reference_precedes_origin(
    target: TableKey,
    origin: _FreshTable,
    section: int,
    definitions: dict[tuple[int, TableKey], tuple[_Definition, ...]],
    referenced_columns: frozenset[str] | None,
) -> bool:
    return not any(
        definition.start > origin.start
        and (referenced_columns is None or definition.columns is None or referenced_columns == definition.columns)
        for (candidate_section, candidate), positions in definitions.items()
        if candidate_section == section
        and (
            candidate[-2:] == target[-2:] or (candidate[-1] == target[-1] and (len(candidate) == 1 or len(target) == 1))
        )
        for definition in positions
    )


def _after_unique_nulls(tokens: list[Token], cursor: int) -> int:
    if sequence(tokens, cursor, ("NULLS", "NOT", "DISTINCT")):
        return cursor + 3
    return cursor + 2 if sequence(tokens, cursor, ("NULLS", "DISTINCT")) else cursor


def _column_list(tokens: list[Token], opening: int) -> tuple[frozenset[str], int] | None:
    if opening >= len(tokens) or tokens[opening].text != "(":
        return None
    closing = matching_paren(tokens, opening)
    if closing is None:
        return None
    columns = tokens[opening + 1 : closing]
    if (
        not columns
        or any(
            not is_identifier_token(token) if index % 2 == 0 else token.text != ","
            for index, token in enumerate(columns)
        )
        or len(columns) % 2 == 0
    ):
        return None
    names = [identifier([token], 0) for token in columns[::2]]
    return frozenset(name[0][0] for name in names if name is not None), closing + 1


def _plain_unique_index(tokens: list[Token]) -> _UniqueIndex | None:
    if not sequence(tokens, 0, ("CREATE", "UNIQUE", "INDEX")):
        return None
    name = identifier(tokens, 3)
    if name is None or len(name[0]) != 1 or not consume(tokens, name[1], "ON"):
        return None
    parsed = identifier(tokens, name[1] + 1)
    if parsed is None:
        return None
    table, opening = parsed
    columns = _column_list(tokens, opening)
    return _UniqueIndex(name[0], table, columns[0]) if columns is not None and columns[1] == len(tokens) else None


def _index_consumers(statements: tuple[_Statement, ...]) -> _IndexConsumers:
    exact: dict[TableKey, int] = {}
    by_name: dict[str, int] = {}
    for statement in statements:
        for consumed in _consumed_indexes(statement.tokens):
            exact[consumed] = statement.start
            by_name[consumed[-1]] = statement.start
    return _IndexConsumers(exact, by_name)


def _has_later_index_consumer(indexed: _UniqueIndex, start: int, consumers: _IndexConsumers) -> bool:
    index_name = (*indexed.table[:-1], *indexed.name)
    if len(index_name) == 1:
        return consumers.by_name.get(index_name[0], -1) > start
    return max(consumers.exact.get(index_name, -1), consumers.exact.get(indexed.name, -1)) > start


def _consumed_indexes(tokens: list[Token]) -> Iterator[TableKey]:
    if sequence(tokens, 0, ("ALTER", "INDEX")) or sequence(tokens, 0, ("DROP", "INDEX")):
        cursor = 2
        if consume(tokens, cursor, "CONCURRENTLY"):
            cursor += 1
        if sequence(tokens, cursor, ("IF", "EXISTS")):
            cursor += 2
        while (parsed := identifier(tokens, cursor)) is not None:
            yield parsed[0]
            cursor = parsed[1]
            if cursor >= len(tokens) or tokens[cursor].text != ",":
                break
            cursor += 1
    if table_actions(tokens) is not None:
        top = top_level_tokens(tokens)
        for cursor in range(len(top)):
            if sequence(top, cursor, ("USING", "INDEX")) and (parsed := identifier(top, cursor + 2)) is not None:
                yield parsed[0]


def _preserves_fresh_tables(tokens: list[Token]) -> bool:
    return (
        sequence(tokens, 0, ("SET", "LOCAL", "LOCK_TIMEOUT"))
        or sequence(tokens, 0, ("SET", "LOCAL", "STATEMENT_TIMEOUT"))
        or sequence(tokens, 0, ("CREATE", "INDEX"))
        or sequence(tokens, 0, ("CREATE", "UNIQUE", "INDEX"))
    )
