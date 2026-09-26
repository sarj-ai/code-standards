from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from sarj_standards.libs.yaml_boundary import mapping_items, sequence_items

from . import manifest, transaction


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


_EXACT_VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")


def retain_previous_approvals(
    files: transaction.FileTransaction, originals: Mapping[Path, bytes | None]
) -> tuple[tuple[Path, str], ...]:
    restore: list[tuple[Path, str]] = []
    for path, original in originals.items():
        if path.name != "pnpm-workspace.yaml" or original is None or path not in files.written:
            continue
        canonical_bytes = files.written[path]
        if canonical_bytes is None:
            continue
        canonical = canonical_bytes.decode("utf-8")
        temporary = _retain_exact_approvals(original.decode("utf-8"), canonical)
        if temporary != canonical:
            files.write_text(path, temporary)
            restore.append((path, canonical))
    return tuple(restore)


def _retain_exact_approvals(original: str, canonical: str) -> str:
    previous = _approvals(original)
    current = _approvals(canonical)
    owned = manifest.eslint_age_gate_preapprovals()
    retained = sorted(
        approval
        for approval in previous - current
        if (parts := approval.rsplit("@", 1))[0] in owned
        and parts[0].startswith("@sarj/")
        and _EXACT_VERSION.fullmatch(parts[-1])
        and f"{parts[0]}@{owned[parts[0]]}" in current
    )
    if not retained:
        return canonical
    node = _approval_sequence(canonical)
    if node is None:
        msg = "cannot locate authored PNPM age approvals"
        raise ValueError(msg)
    position = node.start_mark.index
    if canonical[position] == "[":
        additions = ", ".join(json.dumps(value) for value in retained) + ", "
        return canonical[: position + 1] + additions + canonical[position + 1 :]
    if canonical[position] != "-":
        msg = "cannot temporarily extend anchored PNPM age approvals"
        raise ValueError(msg)
    indent = " " * node.start_mark.column
    additions = "".join(f"- {json.dumps(value)}\n{indent}" for value in retained)
    return canonical[:position] + additions + canonical[position:]


def _approvals(source: str) -> frozenset[str]:
    node = _approval_sequence(source)
    if node is None:
        return frozenset()
    return frozenset(_scalar_text(item) for item in sequence_items(node) if isinstance(item, ScalarNode))


def _approval_sequence(source: str) -> SequenceNode | None:
    try:
        node: object = yaml.compose(source, Loader=yaml.SafeLoader)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType] -- PyYAML parser boundary.
    except yaml.YAMLError as exc:
        msg = "invalid PNPM age approval policy"
        raise ValueError(msg) from exc
    if isinstance(node, MappingNode):
        for key, value in mapping_items(node):
            if (
                isinstance(key, ScalarNode)
                and _scalar_text(key) == "minimumReleaseAgeExclude"
                and isinstance(value, SequenceNode)
                and value.start_mark.index > key.end_mark.index
            ):
                return value
    return None


def _scalar_text(node: ScalarNode) -> str:
    return node.value  # pyright: ignore[reportAny] -- PyYAML scalar boundary.
