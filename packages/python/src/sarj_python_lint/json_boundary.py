import json
from typing import TypeIs


def parse_json(text: str) -> object:
    try:
        return json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_invalid_constant)  # pyright: ignore[reportAny] -- untyped stdlib parser boundary.
    except RecursionError as error:
        message = "JSON nesting exceeds the supported depth"
        raise ValueError(message) from error


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            message = f"duplicate JSON key: {key}"
            raise ValueError(message)
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    message = f"non-finite JSON constant: {value}"
    raise ValueError(message)


def is_object_mapping(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)
