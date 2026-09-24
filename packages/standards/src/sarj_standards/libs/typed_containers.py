from typing import TypeIs


def is_object_mapping(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)


def is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def is_object_tuple(value: object) -> TypeIs[tuple[object, ...]]:
    return isinstance(value, tuple)
