import json
import math
import re

from pydantic import JsonValue, RootModel


_JSON_WHITESPACE = re.compile(r"[ \t\r\n]+")


class _JsonInstance(RootModel[JsonValue]):
    pass


def normalize_json_value(value: object) -> JsonValue:
    return _JsonInstance.model_validate(value).root


def parse_json(text: str) -> JsonValue:
    return json.loads(text)  # pyright: ignore[reportAny] -- untyped parser boundary.


def parse_json_documents(text: str) -> list[JsonValue]:
    decoder = json.JSONDecoder(
        object_pairs_hook=_unique_pairs, parse_constant=_reject_json_constant, parse_float=_finite_json_float
    )
    documents: list[JsonValue] = []
    offset = 0
    while offset < len(text):
        if text[offset] in " \t\r\n":
            offset += 1
            if offset == len(text):
                break
            if text[offset] in " \t\r\n":
                if (whitespace := _JSON_WHITESPACE.match(text, offset)) is not None:
                    offset = whitespace.end()
                if offset == len(text):
                    break
        decoded: tuple[JsonValue, int] = decoder.raw_decode(text, offset)
        document, offset = decoded
        documents.append(document)
    return documents


def parse_unique_json(text: str) -> JsonValue:
    return json.loads(  # pyright: ignore[reportAny] -- stdlib validates the JSON grammar; callbacks refuse ambiguous objects and nonfinite numbers.
        text, object_pairs_hook=_unique_pairs, parse_constant=_reject_json_constant, parse_float=_finite_json_float
    )


def _finite_json_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        msg = f"non-finite JSON number: {value}"
        raise ValueError(msg)
    return number


def _reject_json_constant(value: str) -> None:
    msg = f"non-finite JSON constant: {value}"
    raise ValueError(msg)


def _unique_pairs[T](pairs: list[tuple[str, T]]) -> dict[str, T]:
    result: dict[str, T] = {}
    for key, value in pairs:
        if key in result:
            msg = f"duplicate JSON key: {key}"
            raise ValueError(msg)
        result[key] = value
    return result


def decode_json_prefix(decoder: json.JSONDecoder, text: str) -> object:
    decoded: tuple[object, int] = decoder.raw_decode(text)
    return decoded[0]
