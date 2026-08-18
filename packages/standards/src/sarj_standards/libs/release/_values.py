from __future__ import annotations

from typing import TypeIs


def is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def is_object_dict(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)


def string_object_dict(value: object, *, label: str) -> dict[str, object]:
    if not is_object_dict(value):
        msg = f"{label} must contain an object or table"
        raise TypeError(msg)
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            msg = f"{label} contains a non-string key"
            raise TypeError(msg)
        result[key] = item
    return result
