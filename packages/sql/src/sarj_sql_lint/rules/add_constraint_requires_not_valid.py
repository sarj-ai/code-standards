from __future__ import annotations

from pathlib import PurePosixPath
import re
from typing import TYPE_CHECKING, NamedTuple, final, override

from sarj_sql_lint.rule_base import (
    AutofixPolicy,
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
    locate,
    mask_sql_literals_and_comments,
    split_statements,
)


if TYPE_CHECKING:
    from pathlib import Path


_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_SAFE_BETWEEN_CREATE_AND_ALTER = frozenset({"COMMENT", "CREATE", "DROP", "GRANT", "REVOKE", "SET"})


class _Token(NamedTuple):
    text: str
    start: int
    quoted: bool = False


type _TableKey = tuple[str, ...]


@final
class AddConstraintRequiresNotValid(Rule):
    id = "existing-table-check-or-foreign-key-requires-not-valid"
    code = "SARJ111"
    documentation = RuleDocumentation(
        summary="CHECK and foreign-key constraints added to existing PostgreSQL tables should defer validation.",
        rationale=(
            "Validating a CHECK or foreign key while adding it scans existing rows while PostgreSQL holds locks "
            "that can block writes to the altered table and, for a foreign key, the referenced table."
        ),
        remediation=(
            "Add the constraint with NOT VALID and commit that migration or transaction. Validate it in a later "
            "committed migration or transaction so the lower-lock validation scan does not inherit the ADD lock."
        ),
        category=RuleCategory.PERFORMANCE,
        autofix=AutofixPolicy.NONE,
        aliases=(
            "add-constraint-not-valid",
            "add-constraint-requires-not-valid",
            "existing-table-check-or-fk-requires-not-valid",
        ),
        limitations=(
            "Only PostgreSQL migration files and ALTER TABLE actions that directly add CHECK or foreign-key constraints are inspected.",
            "A table is treated as fresh only after an unconditional empty CREATE TABLE in the same migration section; ambiguous or populating statements revoke that exemption.",
            "Validation transactions are not inferred; the diagnostic explains that VALIDATE CONSTRAINT belongs in a later committed migration or transaction.",
        ),
        examples=(
            RuleExample(
                example_id="validating-check-constraint",
                title="Constraint validated while it is added",
                outcome=ExampleOutcome.MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_age.sql",
                        "ALTER TABLE public.users ADD CONSTRAINT check_age CHECK (age >= 18);\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_age.sql"),
                expected_count=1,
                public=True,
            ),
            RuleExample(
                example_id="deferred-check-validation",
                title="Constraint validation is deferred to a later migration",
                outcome=ExampleOutcome.NO_MATCH,
                files=(
                    ExampleFile.sql(
                        "supabase/migrations/001_age.sql",
                        "ALTER TABLE public.users ADD CONSTRAINT check_age CHECK (age >= 18) NOT VALID;\n",
                    ),
                    ExampleFile.sql(
                        "supabase/migrations/002_validate_age.sql",
                        "ALTER TABLE public.users VALIDATE CONSTRAINT check_age;\n",
                    ),
                ),
                focus_path=PurePosixPath("supabase/migrations/001_age.sql"),
                expected_count=0,
                public=True,
            ),
        ),
    )
    description = documentation.summary

    @override
    def check(self, path: Path, source: str) -> list[Diagnostic]:
        if (
            is_dump_file(source, path)
            or is_generated_migration(path, source)
            or not is_postgres_migration(path, source)
        ):
            return []

        diags: list[Diagnostic] = []
        masked = mask_sql_literals_and_comments(source)
        fresh_tables: set[_TableKey] = set()
        for statement in split_statements(masked):
            text = "\n".join(fragment for _, fragment in statement)
            tokens = _tokenize(text)
            if tokens is None or not tokens:
                fresh_tables.clear()
                continue

            created = _fresh_create_table(tokens)
            if created is not None:
                fresh_tables.add(created)
                continue

            altered = _alter_table(tokens)
            if altered is not None:
                table, actions, can_attach_existing_rows = altered
                if can_attach_existing_rows:
                    fresh_tables.discard(table)
                for action in actions:
                    if table in fresh_tables or _action_has_not_valid(action):
                        continue
                    location = locate(statement, action[0].start)
                    diags.append(
                        Diagnostic(
                            path=path,
                            line=location.line,
                            col=location.column,
                            code=self.code,
                            message=(
                                "Add this CHECK or foreign-key constraint with `NOT VALID`, commit that "
                                "migration or transaction, then run `VALIDATE CONSTRAINT` in a later one."
                            ),
                        )
                    )
                continue

            dropped = _drop_table(tokens)
            if dropped is not None:
                fresh_tables.discard(dropped)
                continue

            if tokens[0].text.upper() not in _SAFE_BETWEEN_CREATE_AND_ALTER:
                # Unknown executable SQL may populate a table through a CTE,
                # function, trigger, or dynamically constructed statement.
                fresh_tables.clear()

        return diags


def _tokenize(text: str) -> list[_Token] | None:
    tokens: list[_Token] = []
    depth = 0
    cursor = 0
    while cursor < len(text):
        char = text[cursor]
        if char.isspace():
            cursor += 1
            continue
        if char == '"':
            end = cursor + 1
            while end < len(text):
                if text[end] != '"':
                    end += 1
                    continue
                if end + 1 < len(text) and text[end + 1] == '"':
                    end += 2
                    continue
                break
            if end >= len(text):
                return None
            tokens.append(_Token(text[cursor : end + 1], cursor, quoted=True))
            cursor = end + 1
            continue
        if (word := _WORD.match(text, cursor)) is not None:
            tokens.append(_Token(word.group(0), cursor))
            cursor = word.end()
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return None
        tokens.append(_Token(char, cursor))
        cursor += 1
    return tokens if depth == 0 else None


def _fresh_create_table(tokens: list[_Token]) -> _TableKey | None:
    cursor = 0
    if not _consume(tokens, cursor, "CREATE"):
        return None
    cursor += 1
    if _consume(tokens, cursor, "GLOBAL") or _consume(tokens, cursor, "LOCAL"):
        cursor += 1
    if (
        _consume(tokens, cursor, "TEMP")
        or _consume(tokens, cursor, "TEMPORARY")
        or _consume(tokens, cursor, "UNLOGGED")
    ):
        cursor += 1
    if not _consume(tokens, cursor, "TABLE"):
        return None
    cursor += 1
    if _sequence(tokens, cursor, ("IF", "NOT", "EXISTS")):
        return None
    parsed = _identifier(tokens, cursor)
    if parsed is None:
        return None
    table, cursor = parsed
    if any(token.text.upper() == "AS" for token in _top_level_tokens(tokens[cursor:])):
        return None
    # A regular CREATE TABLE must contain a definition list. Requiring it also
    # keeps malformed or partial statements from manufacturing an exemption.
    return table if cursor < len(tokens) and tokens[cursor].text == "(" else None


def _alter_table(tokens: list[_Token]) -> tuple[_TableKey, list[list[_Token]], bool] | None:
    if not _sequence(tokens, 0, ("ALTER", "TABLE")):
        return None
    cursor = 2
    if _sequence(tokens, cursor, ("IF", "EXISTS")):
        cursor += 2
    if _consume(tokens, cursor, "ONLY"):
        cursor += 1
    parsed = _identifier(tokens, cursor)
    if parsed is None:
        return None
    table, cursor = parsed
    if cursor < len(tokens) and tokens[cursor].text == "*":
        cursor += 1
    segments = _split_actions(tokens[cursor:])
    if segments is None:
        return None
    return (
        table,
        [segment for segment in segments if _is_validating_add_action(segment)],
        any(_sequence(segment, 0, ("ATTACH", "PARTITION")) for segment in segments),
    )


def _drop_table(tokens: list[_Token]) -> _TableKey | None:
    if not _sequence(tokens, 0, ("DROP", "TABLE")):
        return None
    cursor = 2
    if _sequence(tokens, cursor, ("IF", "EXISTS")):
        cursor += 2
    parsed = _identifier(tokens, cursor)
    return None if parsed is None else parsed[0]


def _identifier(tokens: list[_Token], cursor: int) -> tuple[_TableKey, int] | None:
    parts: list[str] = []
    while cursor < len(tokens):
        token = tokens[cursor]
        if not token.quoted and _WORD.fullmatch(token.text) is None:
            return None
        if token.quoted:
            decoded = token.text[1:-1].replace('""', '"')
            parts.append(f"q:{decoded}")
        else:
            parts.append(f"u:{token.text.lower()}")
        cursor += 1
        if cursor >= len(tokens) or tokens[cursor].text != ".":
            break
        cursor += 1
    return (tuple(parts), cursor) if parts else None


def _split_actions(tokens: list[_Token]) -> list[list[_Token]] | None:
    if not tokens:
        return None
    actions: list[list[_Token]] = []
    current: list[_Token] = []
    depth = 0
    for token in tokens:
        if token.text == "(":
            depth += 1
        elif token.text == ")":
            depth -= 1
            if depth < 0:
                return None
        if token.text == "," and depth == 0:
            if not current:
                return None
            actions.append(current)
            current = []
            continue
        current.append(token)
    if depth != 0 or not current:
        return None
    actions.append(current)
    return actions


def _is_validating_add_action(action: list[_Token]) -> bool:
    if not action or action[0].text.upper() != "ADD":
        return False
    cursor = 1
    if _consume(action, cursor, "CONSTRAINT"):
        cursor += 1
        if cursor >= len(action) or not _is_identifier_token(action[cursor]):
            return False
        cursor += 1
        if cursor < len(action) and action[cursor].text == ".":
            return False
    if _consume(action, cursor, "CHECK"):
        if cursor + 1 >= len(action) or action[cursor + 1].text != "(":
            return False
        close = _matching_paren(action, cursor + 1)
        return close is not None and close > cursor + 2
    if not _sequence(action, cursor, ("FOREIGN", "KEY")):
        return False
    columns_open = cursor + 2
    if columns_open >= len(action) or action[columns_open].text != "(":
        return False
    columns_close = _matching_paren(action, columns_open)
    if columns_close is None or not _valid_identifier_list(action[columns_open + 1 : columns_close]):
        return False
    references = next(
        (index for index in range(columns_close + 1, len(action)) if _consume(action, index, "REFERENCES")),
        None,
    )
    if references is None:
        return False
    referenced_table = _identifier(action, references + 1)
    if referenced_table is None:
        return False
    _, referenced_columns_open = referenced_table
    if referenced_columns_open >= len(action) or action[referenced_columns_open].text != "(":
        return False
    referenced_columns_close = _matching_paren(action, referenced_columns_open)
    return referenced_columns_close is not None and _valid_identifier_list(
        action[referenced_columns_open + 1 : referenced_columns_close]
    )


def _valid_identifier_list(tokens: list[_Token]) -> bool:
    expect_identifier = True
    for token in tokens:
        if expect_identifier:
            if not _is_identifier_token(token):
                return False
        elif token.text != ",":
            return False
        expect_identifier = not expect_identifier
    return bool(tokens) and not expect_identifier


def _is_identifier_token(token: _Token) -> bool:
    return token.quoted or _WORD.fullmatch(token.text) is not None


def _matching_paren(tokens: list[_Token], opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(tokens)):
        if tokens[index].text == "(":
            depth += 1
        elif tokens[index].text == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _action_has_not_valid(action: list[_Token]) -> bool:
    depth = 0
    for index, token in enumerate(action[:-1]):
        if token.text == "(":
            depth += 1
            continue
        if token.text == ")":
            depth -= 1
            continue
        if depth == 0 and token.text.upper() == "NOT" and action[index + 1].text.upper() == "VALID":
            return True
    return False


def _top_level_tokens(tokens: list[_Token]) -> list[_Token]:
    found: list[_Token] = []
    depth = 0
    for token in tokens:
        if token.text == "(":
            depth += 1
        elif token.text == ")":
            depth -= 1
        elif depth == 0:
            found.append(token)
    return found


def _consume(tokens: list[_Token], cursor: int, expected: str) -> bool:
    return cursor < len(tokens) and not tokens[cursor].quoted and tokens[cursor].text.upper() == expected


def _sequence(tokens: list[_Token], cursor: int, expected: tuple[str, ...]) -> bool:
    return all(_consume(tokens, cursor + offset, word) for offset, word in enumerate(expected))
