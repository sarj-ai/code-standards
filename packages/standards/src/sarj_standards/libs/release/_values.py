from __future__ import annotations

from sarj_standards.libs.typed_containers import (
    is_object_list as is_object_list,
    is_object_mapping,
)


is_object_dict = is_object_mapping


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
