from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import json
from typing import TYPE_CHECKING, TypeIs

from sarj_rule_contracts import RuleId


if TYPE_CHECKING:
    from sarj_python_lint.rule_base import Rule


DESCRIPTOR_SCHEMA_VERSION = 1
_MAX_GENERATED_LINE_LENGTH = 120


@dataclass(frozen=True, slots=True)
class RuleDescriptor:
    rule_id: RuleId
    module: str
    class_name: str
    code: str
    description: str
    aliases: tuple[str, ...]
    enabled_by_default: bool

    def __post_init__(self) -> None:
        for value in (self.rule_id, self.module, self.class_name, self.code, self.description):
            if not _nonempty_text(value):
                msg = "rule descriptor text fields must be nonempty strings"
                raise TypeError(msg)
        if not is_alias_tuple(self.aliases):
            msg = "rule descriptor aliases must be an immutable string tuple"
            raise TypeError(msg)
        if type(self.enabled_by_default) is not bool:
            msg = "rule descriptor enabled_by_default must be a bool"
            raise TypeError(msg)


def _object_tuple(value: object) -> TypeIs[tuple[object, ...]]:
    return isinstance(value, tuple)


def _nonempty_text(value: object) -> TypeIs[str]:
    return isinstance(value, str) and bool(value)


def is_alias_tuple(value: object) -> TypeIs[tuple[str, ...]]:
    return _object_tuple(value) and all(isinstance(item, str) for item in value)


def load_descriptors() -> tuple[RuleDescriptor, ...]:
    module = import_module("sarj_python_lint._rule_descriptors")
    version: object = (
        getattr(  # sarj-noqa: SARJ557 -- Validate imported plugin metadata before trusting its declared rule contract.
            module, "SCHEMA_VERSION", None
        )
    )
    if type(version) is not int or version != DESCRIPTOR_SCHEMA_VERSION:
        msg = "unsupported Python rule descriptor schema"
        raise ValueError(msg)
    value: object = (
        getattr(  # sarj-noqa: SARJ557 -- Validate imported plugin metadata before trusting its declared rule contract.
            module, "DESCRIPTORS", None
        )
    )
    if not _object_tuple(value):
        msg = "Python rule descriptors must be a tuple"
        raise TypeError(msg)
    result: list[RuleDescriptor] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, RuleDescriptor):
            msg = "Python rule descriptor entries must be RuleDescriptor records"
            raise TypeError(msg)
        if item.rule_id in seen:
            msg = f"duplicate Python rule descriptor: {item.rule_id}"
            raise ValueError(msg)
        seen.add(item.rule_id)
        result.append(item)
    return tuple(result)


def authored_descriptors() -> tuple[RuleDescriptor, ...]:
    from sarj_python_lint.rules._registry import (  # ruff: ignore[import-outside-top-level] -- generation owns eager source imports and must not depend on generated data.
        _AUTHORING_DEFAULT_REGISTRY,  # pyright: ignore[reportPrivateUsage] -- the independent authoring table remains private to source-maintenance consumers.
        _AUTHORING_REGISTRY,  # pyright: ignore[reportPrivateUsage] -- reading the eager oracle must not consult the generated runtime table.
    )

    descriptors = tuple(_authored_descriptor(RuleId(rule_id), rule) for rule_id, rule in _AUTHORING_REGISTRY.items())
    expected_defaults = tuple(item.rule_id for item in descriptors if item.enabled_by_default)
    if tuple(_AUTHORING_DEFAULT_REGISTRY) != expected_defaults:
        msg = "Python authoring default registry differs from source-owned rule metadata"
        raise ValueError(msg)
    return descriptors


def _authored_descriptor(rule_id: RuleId, rule: type[Rule]) -> RuleDescriptor:
    documentation = rule.documentation
    if documentation is None:
        msg = f"{rule_id}: source-owned documentation is required for descriptors"
        raise ValueError(msg)
    if rule.id != rule_id or documentation.summary != rule.description:
        msg = f"{rule_id}: source-owned class metadata is inconsistent"
        raise ValueError(msg)
    instance = rule()
    if instance.code != rule.code or instance.description != rule.description:
        msg = f"{rule_id}: instance metadata differs from class metadata"
        raise ValueError(msg)
    module = import_module(rule.__module__)
    if (
        getattr(  # sarj-noqa: SARJ557 -- Validate imported plugin metadata before trusting its declared rule contract.
            module, rule.__name__, None
        )
        is not rule
    ):
        msg = f"{rule_id}: rule class is not importable from its declared module"
        raise ValueError(msg)
    return RuleDescriptor(
        rule_id,
        rule.__module__,
        rule.__name__,
        rule.code,
        rule.description,
        tuple(documentation.aliases),
        rule.enabled_by_default,
    )


def render_authored_descriptors() -> str:
    lines = [
        "# Generated from the eager source registry; use maintain rules sync to update.",
        "from __future__ import annotations",
        "",
        "from sarj_rule_contracts import RuleId",
        "",
        "from sarj_python_lint.rule_metadata import RuleDescriptor",
        "",
        "",
        f"SCHEMA_VERSION = {DESCRIPTOR_SCHEMA_VERSION}",
        "DESCRIPTORS: tuple[RuleDescriptor, ...] = (",
    ]
    for item in authored_descriptors():
        aliases = ", ".join(json.dumps(alias, ensure_ascii=False) for alias in item.aliases)
        if len(item.aliases) == 1:
            aliases += ","
        alias_lines = [f"        aliases=({aliases}),"]
        if len(alias_lines[0]) > _MAX_GENERATED_LINE_LENGTH:
            alias_lines = [
                "        aliases=(",
                *(f"            {json.dumps(alias, ensure_ascii=False)}," for alias in item.aliases),
                "        ),",
            ]
        lines.extend(
            (
                "    RuleDescriptor(",
                f"        rule_id=RuleId({json.dumps(item.rule_id, ensure_ascii=False)}),",
                f"        module={json.dumps(item.module, ensure_ascii=False)},",
                f"        class_name={json.dumps(item.class_name, ensure_ascii=False)},",
                f"        code={json.dumps(item.code, ensure_ascii=False)},",
                f"        description={json.dumps(item.description, ensure_ascii=False)},",
                *alias_lines,
                f"        enabled_by_default={item.enabled_by_default},",
                "    ),",
            )
        )
    lines.extend((")", ""))
    return "\n".join(lines)
