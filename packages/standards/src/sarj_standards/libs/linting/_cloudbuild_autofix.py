from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

from sarj_rule_contracts import TextEdit, apply_edits
import yaml
from yaml.nodes import MappingNode, SequenceNode

from sarj_standards.libs.json_boundary import parse_unique_json
from sarj_standards.libs.linting.cloudbuild import (
    check_cloudbuild,
    compose_documents,
    mapping_fields,
    scalar_text,
)
from sarj_standards.libs.linting.text_rule_base import Finding
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping
from sarj_standards.libs.yaml_boundary import parse_yaml_documents, sequence_items


if TYPE_CHECKING:
    from pathlib import Path


_AMBIGUOUS_YAML = re.compile(r"(?m)(?:^[\ufeff \t]*%|(?:^|[\s\[\]{},:])(?:[&*!]|<<[ \t]*:))")
_SENTINEL_MESSAGE = "Cloud Build waitFor '-' must be the sole dependency"
_CODE = "SARJ315"
_MIN_DUPLICATES = 2
_SPELLINGS = frozenset({"'-'", '"-"', "-"})


@dataclass(frozen=True, slots=True)
class _Repair:
    document: int
    step: int
    edit: TextEdit
    findings: tuple[Finding, ...]


def fix_cloudbuild_sentinels(path: Path, source: str) -> str:
    if path.suffix.lower() not in {".yaml", ".yml", ".json"} or "#" in source or _AMBIGUOUS_YAML.search(source):
        return source
    try:
        return _fix_owned_sentinels(path, source)
    except ValueError, TypeError, RecursionError, yaml.YAMLError:
        return source


def _fix_owned_sentinels(path: Path, source: str) -> str:
    json_values = _parsed_values(path, source) if path.suffix.lower() == ".json" else None
    repairs = _repairs(path, source)
    if not repairs:
        return source
    before = Counter(check_cloudbuild(path, source))
    removed = Counter(finding for repair in repairs for finding in repair.findings)
    if removed - before:
        return source
    fixed = apply_edits(source, [repair.edit for repair in repairs])
    targets = {(repair.document, repair.step) for repair in repairs}
    original_values = parse_yaml_documents(source) if json_values is None else json_values
    expected = _expected_values(original_values, targets)
    if _parsed_values(path, fixed) != expected or Counter(check_cloudbuild(path, fixed)) != before - removed:
        return source
    return fixed


def _parsed_values(
    path: Path, source: str
) -> tuple[  # sarj-noqa: SARJ528 -- Preserve native YAML values for autofix equivalence.
    object, ...
]:
    return (parse_unique_json(source),) if path.suffix.lower() == ".json" else parse_yaml_documents(source)


def _repairs(path: Path, source: str) -> list[_Repair]:
    repairs: list[_Repair] = []
    for document_index, document in enumerate(compose_documents(source)):
        steps = mapping_fields(document).get("steps") if isinstance(document, MappingNode) else None
        if not isinstance(steps, SequenceNode):
            continue
        for step_index, step in enumerate(sequence_items(steps)):
            if not isinstance(step, MappingNode):
                continue
            waits = mapping_fields(step).get("waitFor")
            if isinstance(waits, SequenceNode) and (edit := _sentinel_edit(source, waits)) is not None:
                repairs.append(
                    _Repair(
                        document=document_index,
                        step=step_index,
                        edit=edit,
                        findings=tuple(_sentinel_findings(path, step, waits)),
                    )
                )
    return repairs


def _sentinel_edit(source: str, waits: SequenceNode) -> TextEdit | None:
    nodes = sequence_items(waits)
    if not waits.flow_style or len(nodes) < _MIN_DUPLICATES or any(scalar_text(node) != "-" for node in nodes):
        return None
    if any(source[node.start_mark.index : node.end_mark.index] not in _SPELLINGS for node in nodes):
        return None
    start, end = waits.start_mark.index, waits.end_mark.index
    if source[start : start + 1] != "[" or source[end - 1 : end] != "]":
        return None
    first_end = nodes[0].end_mark.index
    tail = source[first_end : end - 1]
    whitespace = "".join(character for character in tail if character in " \t\r\n")
    if source[nodes[0].start_mark.index : first_end] == "-":
        whitespace = "," + whitespace if "\r" in whitespace or "\n" in whitespace else ""
    return TextEdit(start, end, source[start:first_end] + whitespace + "]")


def _sentinel_findings(path: Path, step: MappingNode, waits: SequenceNode) -> list[Finding]:
    return [
        Finding(path, max(step.start_mark.line, node.start_mark.line) + 1, _CODE, _SENTINEL_MESSAGE)
        for node in sequence_items(waits)
    ]


def _expected_values(
    documents: tuple[  # sarj-noqa: SARJ528 -- Preserve untouched native YAML values across targeted rewrites.
        object, ...
    ],
    targets: set[tuple[int, int]],
) -> tuple[  # sarj-noqa: SARJ528 -- Preserve untouched native YAML values across targeted rewrites.
    object, ...
]:
    return tuple(
        _expected_document(value, {step for index, step in targets if index == document})
        for document, value in enumerate(documents)
    )


def _expected_document(
    value: object,  # sarj-noqa: SARJ528 -- Only rewrite steps; preserve other native YAML values.
    targets: set[int],
) -> object:  # sarj-noqa: SARJ528 -- Only rewrite steps; preserve other native YAML values.
    if not is_object_mapping(value) or not is_object_list(steps := value.get("steps")):
        return value
    return {**value, "steps": [_expected_step(step) if index in targets else step for index, step in enumerate(steps)]}


def _expected_step(value: object) -> object:  # sarj-noqa: SARJ528 -- Preserve native YAML fields outside waitFor.
    return {**value, "waitFor": ["-"]} if is_object_mapping(value) else value
