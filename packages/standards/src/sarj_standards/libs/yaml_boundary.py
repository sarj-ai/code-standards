from __future__ import annotations

from typing import TYPE_CHECKING

import yaml


if TYPE_CHECKING:
    from yaml.nodes import MappingNode, Node, SequenceNode


def parse_yaml(text: str) -> object:
    return yaml.safe_load(text)  # pyright: ignore[reportAny] -- untyped parser boundary.


def mapping_items(node: MappingNode) -> list[tuple[Node, Node]]:
    return node.value  # pyright: ignore[reportAny] -- PyYAML's node value lacks a typed stub.


def sequence_items(node: SequenceNode) -> list[Node]:
    return node.value  # pyright: ignore[reportAny] -- PyYAML's node value lacks a typed stub.
