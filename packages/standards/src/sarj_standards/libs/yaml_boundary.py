from __future__ import annotations

from typing import TYPE_CHECKING

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode


if TYPE_CHECKING:
    from yaml.nodes import Node


def parse_yaml(text: str) -> object:
    return yaml.safe_load(text)  # pyright: ignore[reportAny] -- untyped parser boundary.


def parse_yaml_documents(text: str) -> tuple[object, ...]:
    nodes: tuple[Node | None, ...] = tuple(yaml.compose_all(text, Loader=yaml.SafeLoader))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType] -- untyped parser boundary.
    for node in nodes:
        _validate_yaml_node(node, set(), 0)
    return tuple(yaml.safe_load_all(text))


_MAX_YAML_DEPTH = 64


def _validate_yaml_node(node: Node | None, visiting: set[int], depth: int) -> None:
    if node is None:
        return
    if depth >= _MAX_YAML_DEPTH or id(node) in visiting:
        msg = "recursive or excessively nested YAML cannot be validated"
        raise ValueError(msg)
    visiting.add(id(node))
    if isinstance(node, MappingNode):
        names: set[tuple[str, str]] = set()
        for key, value in mapping_items(node):
            if not isinstance(key, ScalarNode):
                msg = "configuration keys must be scalar"
                raise TypeError(msg)
            identity = (key.tag, _scalar_value(key))
            if identity in names:
                msg = f"duplicate YAML key: {identity[1]}"
                raise ValueError(msg)
            names.add(identity)
            _validate_yaml_node(value, visiting, depth + 1)
    elif isinstance(node, SequenceNode):
        for item in sequence_items(node):
            _validate_yaml_node(item, visiting, depth + 1)
    visiting.remove(id(node))


def _scalar_value(node: ScalarNode) -> str:
    value: object = node.value  # pyright: ignore[reportAny] -- PyYAML scalar parser boundary.
    if not isinstance(value, str):
        msg = "YAML scalar node value must be text"
        raise TypeError(msg)
    return value


def mapping_items(node: MappingNode) -> list[tuple[Node, Node]]:
    return node.value  # pyright: ignore[reportAny] -- PyYAML's node value lacks a typed stub.


def sequence_items(node: SequenceNode) -> list[Node]:
    return node.value  # pyright: ignore[reportAny] -- PyYAML's node value lacks a typed stub.
