from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode


if TYPE_CHECKING:
    from yaml.nodes import Node


def parse_yaml(text: str) -> object:
    return yaml.safe_load(text)  # pyright: ignore[reportAny] -- untyped parser boundary.


def parse_yaml_documents(text: str) -> tuple[object, ...]:
    loader = yaml.SafeLoader(text)
    documents: list[object] = []
    try:
        while loader.check_data():  # pyright: ignore[reportUnknownMemberType] -- untyped parser boundary.
            if (node := loader.get_node()) is not None:
                _YamlValidation(loader).shape(node, 0)
                documents.append(loader.construct_document(node))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType] -- validated PyYAML construction boundary.
    except RecursionError as error:
        msg = "excessively nested YAML cannot be validated"
        raise ValueError(msg) from error
    finally:
        loader.dispose()  # pyright: ignore[reportUnknownMemberType] -- untyped parser lifetime boundary.
    return tuple(documents)


_MAX_YAML_DEPTH = 64
_MAX_YAML_EXPANDED_NODES = 100_000


class _YamlShape(NamedTuple):
    height: int
    expanded_nodes: int


@dataclass(slots=True)
class _YamlValidation:
    loader: yaml.SafeLoader
    visiting: set[int] = field(default_factory=set)
    shapes: dict[int, _YamlShape] = field(default_factory=dict)

    def shape(self, node: Node, depth: int) -> _YamlShape:
        if depth >= _MAX_YAML_DEPTH or id(node) in self.visiting:
            msg = "recursive or excessively nested YAML cannot be validated"
            raise ValueError(msg)
        if (cached := self.shapes.get(id(node))) is not None:
            if depth + cached.height >= _MAX_YAML_DEPTH:
                msg = "excessively nested YAML cannot be validated"
                raise ValueError(msg)
            return cached
        self.visiting.add(id(node))
        children = (
            self.mapping_values(node)
            if isinstance(node, MappingNode)
            else sequence_items(node)
            if isinstance(node, SequenceNode)
            else []
        )
        shapes = tuple(self.shape(child, depth + 1) for child in children)
        result = _YamlShape(
            height=1 + max((item.height for item in shapes), default=-1),
            expanded_nodes=1 + sum(item.expanded_nodes for item in shapes),
        )
        if result.expanded_nodes > _MAX_YAML_EXPANDED_NODES:
            msg = "expanded YAML exceeds the 100,000-node analysis bound"
            raise ValueError(msg)
        self.visiting.remove(id(node))
        self.shapes[id(node)] = result
        return result

    def mapping_values(self, node: MappingNode) -> list[Node]:
        names: set[object] = set()
        children: list[Node] = []
        for key, value in mapping_items(node):
            if not isinstance(key, ScalarNode):
                msg = "configuration keys must be scalar"
                raise TypeError(msg)
            identity = self.key_identity(key)
            if identity in names:
                msg = f"duplicate YAML key: {_scalar_value(key)}"
                raise ValueError(msg)
            names.add(identity)
            children.extend((key, value))
        return children

    def key_identity(self, node: ScalarNode) -> object:
        if node.tag == "tag:yaml.org,2002:merge":
            return (node.tag,)
        return self.loader.construct_object(node)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] -- safe scalar construction preserves actual dictionary-key equality.


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
