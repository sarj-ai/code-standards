from __future__ import annotations

import re
from typing import NamedTuple


_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


class Token(NamedTuple):
    text: str
    start: int
    quoted: bool = False


type TableKey = tuple[str, ...]


def tokenize(text: str) -> list[Token] | None:
    tokens: list[Token] = []
    depth = 0
    cursor = 0
    while cursor < len(text):
        char = text[cursor]
        if char.isspace():
            cursor += 1
            continue
        if char == '"':
            end = _quoted_identifier_end(text, cursor)
            if end >= len(text):
                return None
            tokens.append(Token(text[cursor : end + 1], cursor, quoted=True))
            cursor = end + 1
            continue
        if (word := _WORD.match(text, cursor)) is not None:
            tokens.append(Token(word.group(0), cursor))
            cursor = word.end()
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return None
        tokens.append(Token(char, cursor))
        cursor += 1
    return tokens if depth == 0 else None


def fresh_create_table(tokens: list[Token]) -> TableKey | None:
    cursor = 0
    if not consume(tokens, cursor, "CREATE"):
        return None
    cursor += 1
    if consume(tokens, cursor, "GLOBAL") or consume(tokens, cursor, "LOCAL"):
        cursor += 1
    if consume(tokens, cursor, "TEMP") or consume(tokens, cursor, "TEMPORARY") or consume(tokens, cursor, "UNLOGGED"):
        cursor += 1
    if not consume(tokens, cursor, "TABLE"):
        return None
    cursor += 1
    if sequence(tokens, cursor, ("IF", "NOT", "EXISTS")):
        return None
    parsed = identifier(tokens, cursor)
    if parsed is None:
        return None
    table, cursor = parsed
    if any(token.text.upper() == "AS" for token in top_level_tokens(tokens[cursor:])):
        return None
    # A regular CREATE TABLE must contain a definition list. Requiring it also
    # keeps malformed or partial statements from manufacturing an exemption.
    return table if cursor < len(tokens) and tokens[cursor].text == "(" else None


def table_actions(tokens: list[Token]) -> tuple[TableKey, list[list[Token]]] | None:
    if not sequence(tokens, 0, ("ALTER", "TABLE")):
        return None
    cursor = 2
    if sequence(tokens, cursor, ("IF", "EXISTS")):
        cursor += 2
    if consume(tokens, cursor, "ONLY"):
        cursor += 1
    parsed = identifier(tokens, cursor)
    if parsed is None:
        return None
    table, cursor = parsed
    if cursor < len(tokens) and tokens[cursor].text == "*":
        cursor += 1
    segments = split_actions(tokens[cursor:])
    if segments is None:
        return None
    return table, segments


def alter_table(tokens: list[Token]) -> tuple[TableKey, list[list[Token]], bool, TableKey | None] | None:
    parsed = table_actions(tokens)
    if parsed is None:
        return None
    table, segments = parsed
    renamed_to: TableKey | None = None
    if len(segments) == 1 and sequence(segments[0], 0, ("RENAME", "TO")):
        renamed = identifier(segments[0], 2)
        if renamed is not None:
            name, end = renamed
            if len(name) == 1 and end == len(segments[0]):
                renamed_to = (*table[:-1], *name)
    return (
        table,
        [segment for segment in segments if is_validating_add_action(segment)],
        any(sequence(segment, 0, ("ATTACH", "PARTITION")) for segment in segments),
        renamed_to,
    )


def drop_table(tokens: list[Token]) -> TableKey | None:
    if not sequence(tokens, 0, ("DROP", "TABLE")):
        return None
    cursor = 2
    if sequence(tokens, cursor, ("IF", "EXISTS")):
        cursor += 2
    parsed = identifier(tokens, cursor)
    return None if parsed is None else parsed[0]


def identifier(tokens: list[Token], cursor: int) -> tuple[TableKey, int] | None:
    parts: list[str] = []
    while cursor < len(tokens):
        token = tokens[cursor]
        if not token.quoted and _WORD.fullmatch(token.text) is None:
            return None
        if token.quoted:
            decoded = token.text[1:-1].replace('""', '"')
            parts.append(decoded)
        else:
            parts.append(token.text.lower())
        cursor += 1
        if cursor >= len(tokens) or tokens[cursor].text != ".":
            break
        cursor += 1
        if cursor == len(tokens):
            return None
    return (tuple(parts), cursor) if parts else None


def split_actions(tokens: list[Token]) -> list[list[Token]] | None:
    if not tokens:
        return None
    actions: list[list[Token]] = []
    current: list[Token] = []
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


def is_validating_add_action(action: list[Token]) -> bool:
    if not action or action[0].text.upper() != "ADD":
        return False
    cursor = 1
    if consume(action, cursor, "CONSTRAINT"):
        cursor += 1
        if cursor >= len(action) or not is_identifier_token(action[cursor]):
            return False
        cursor += 1
        if cursor < len(action) and action[cursor].text == ".":
            return False
    if consume(action, cursor, "CHECK"):
        if cursor + 1 >= len(action) or action[cursor + 1].text != "(":
            return False
        close = matching_paren(action, cursor + 1)
        return close is not None and close > cursor + 2
    if not sequence(action, cursor, ("FOREIGN", "KEY")):
        return False
    return _is_foreign_key_action(action, cursor)


def is_identifier_token(token: Token) -> bool:
    return token.quoted or _WORD.fullmatch(token.text) is not None


def matching_paren(tokens: list[Token], opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(tokens)):
        if tokens[index].text == "(":
            depth += 1
        elif tokens[index].text == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def top_level_tokens(tokens: list[Token]) -> list[Token]:
    found: list[Token] = []
    depth = 0
    for token in tokens:
        if token.text == "(":
            depth += 1
        elif token.text == ")":
            depth -= 1
        elif depth == 0:
            found.append(token)
    return found


def consume(tokens: list[Token], cursor: int, expected: str) -> bool:
    return cursor < len(tokens) and not tokens[cursor].quoted and tokens[cursor].text.upper() == expected


def sequence(tokens: list[Token], cursor: int, expected: tuple[str, ...]) -> bool:
    return all(consume(tokens, cursor + offset, word) for offset, word in enumerate(expected))


def _quoted_identifier_end(text: str, cursor: int) -> int:
    end = cursor + 1
    while end < len(text):
        if text[end] != '"':
            end += 1
            continue
        if end + 1 < len(text) and text[end + 1] == '"':
            end += 2
            continue
        break
    return end


def _is_foreign_key_action(action: list[Token], cursor: int) -> bool:
    columns_open = cursor + 2
    if columns_open >= len(action) or action[columns_open].text != "(":
        return False
    columns_close = matching_paren(action, columns_open)
    if columns_close is None or not _valid_identifier_list(action[columns_open + 1 : columns_close]):
        return False
    references = next(
        (index for index in range(columns_close + 1, len(action)) if consume(action, index, "REFERENCES")),
        None,
    )
    if references is None:
        return False
    referenced_table = identifier(action, references + 1)
    if referenced_table is None:
        return False
    _, referenced_columns_open = referenced_table
    if referenced_columns_open == len(action):
        return True
    if action[referenced_columns_open].text != "(":
        return any(
            consume(action, referenced_columns_open, keyword)
            for keyword in ("MATCH", "ON", "DEFERRABLE", "INITIALLY", "ENFORCED", "NOT")
        )
    referenced_columns_close = matching_paren(action, referenced_columns_open)
    return referenced_columns_close is not None and _valid_identifier_list(
        action[referenced_columns_open + 1 : referenced_columns_close]
    )


def _valid_identifier_list(tokens: list[Token]) -> bool:
    expect_identifier = True
    for token in tokens:
        if expect_identifier:
            if not is_identifier_token(token):
                return False
        elif token.text != ",":
            return False
        expect_identifier = not expect_identifier
    return bool(tokens) and not expect_identifier
