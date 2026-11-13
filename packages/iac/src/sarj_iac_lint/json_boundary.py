import json
from typing import TypeIs


type JsonValue = str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None


def parse_json(text: str) -> JsonValue:
    return json.loads(text)  # pyright: ignore[reportAny] -- untyped stdlib parser boundary.


def is_object_mapping(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)
