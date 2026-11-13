from json import JSONDecodeError
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.json_boundary import parse_json_documents, parse_unique_json


if TYPE_CHECKING:
    from typing import Final

    from pydantic import JsonValue


_JSON_DOCUMENT_CASES: Final[tuple[tuple[str, list[JsonValue]], ...]] = (
    (" \r\n{}\t", [{}]),
    ("true false null", [True, False, None]),
    ("1 2 -3.5", [1, 2, -3.5]),
    ('" \\t\\r\\n"[]', [" \t\r\n", []]),
)


@pytest.mark.parametrize("number", ["1e999", "-1e999", "NaN", "Infinity", "-Infinity"])
def test_unique_json_refuses_nonfinite_numbers_at_any_depth(number: str) -> None:
    with pytest.raises(ValueError, match="non-finite JSON"):
        parse_unique_json('{"deadlines":[' + number + "]}")


def test_unique_json_preserves_large_finite_numbers_and_literal_text() -> None:
    assert parse_unique_json('{"values":[1e308,-1e308,"1e999"]}') == {"values": [1e308, -1e308, "1e999"]}


def test_unique_json_refuses_duplicate_transition_fields() -> None:
    with pytest.raises(ValueError, match="duplicate JSON key: state"):
        parse_unique_json('{"event":{"state":"pending","state":"complete"}}')


@pytest.mark.parametrize("source", ['[{"state":"open","state":"closed"}] []', '[] [{"deadline":1e999}]'])
def test_paginated_json_refuses_ambiguous_transition_or_deadline(source: str) -> None:
    with pytest.raises(ValueError, match=r"duplicate JSON key|non-finite JSON number"):
        parse_json_documents(source)


@pytest.mark.parametrize("separator", ["", " ", "\t", "\r", "\n", " \t\r\n" * 16_384])
def test_json_documents_preserve_concatenated_values_and_native_whitespace(separator: str) -> None:
    source = separator.join(("{}", "[true, null]", '"a b"'))

    assert parse_json_documents(source) == [{}, [True, None], "a b"]


@pytest.mark.parametrize("source", ["", " ", "\t", "\r", "\n", " \t\r\n" * 16_384])
def test_json_documents_accept_empty_or_whitespace_only_streams(source: str) -> None:
    assert parse_json_documents(source) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    _JSON_DOCUMENT_CASES,
)
def test_json_document_boundaries_preserve_scalars_and_string_contents(source: str, expected: list[JsonValue]) -> None:
    assert parse_json_documents(source) == expected


@pytest.mark.parametrize("separator", ["\u00a0", "\v", "\f", "\u2028", "\u2029", "\ufeff"])
def test_json_document_whitespace_does_not_accept_non_json_separators(separator: str) -> None:
    with pytest.raises(JSONDecodeError) as failure:
        parse_json_documents("{}" + separator + "[]")

    assert failure.value.pos == 2


@pytest.mark.parametrize(("source", "position", "line", "column"), [("{}\r\n \t[", 7, 2, 4), ("{} \n?", 4, 2, 1)])
def test_json_documents_preserve_native_error_locations(source: str, position: int, line: int, column: int) -> None:
    with pytest.raises(JSONDecodeError) as failure:
        parse_json_documents(source)

    assert (failure.value.pos, failure.value.lineno, failure.value.colno) == (position, line, column)
