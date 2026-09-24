import json
from typing import TypeIs


def parse_json(text: str) -> object:
    return json.loads(text)  # pyright: ignore[reportAny] -- untyped stdlib parser boundary.


def is_object_mapping(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)
