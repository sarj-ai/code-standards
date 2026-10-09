from __future__ import annotations

from copy import copy
import re
from typing import TYPE_CHECKING, override

import yaml
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from sarj_standards.libs.linting.text_rule_base import Finding
from sarj_standards.libs.yaml_boundary import mapping_items, sequence_items


if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_CODE = "SARJ315"
_SHELLS = frozenset({"sh", "bash", "dash", "ash", "zsh", "ksh"})
_SUBSTITUTION = re.compile(r"\$(?:\{(?:_[A-Z0-9_]+|[A-Z][A-Z0-9_]*)\}|(?:_[A-Z0-9_]+|[A-Z][A-Z0-9_]*))")
_SAFE_BUILTINS = frozenset({"PROJECT_ID", "BUILD_ID"})
_MAX_YAML_DEPTH = 64
_MAX_YAML_NODES = 100_000
_SHELL_LONG_FLAGS = frozenset(
    {"--norc", "--noprofile", "--posix", "--restricted", "--verbose", "--login", "--noediting"}
)
_SHELL_LONG_VALUES = frozenset({"--rcfile", "--init-file"})


class CloudBuildParseError(ValueError):
    """The caller must expose malformed or ambiguous YAML as a coverage failure."""


class _UseSiteLoader(yaml.SafeLoader):
    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._remaining: int = _MAX_YAML_NODES
        self._depth: int = 0

    @override
    def compose_node(self, parent: Node | None, index: int) -> Node | None:
        self._remaining -= 1
        if self._remaining < 0 or self._depth >= _MAX_YAML_DEPTH:
            message = "YAML composition exceeds analysis node or depth bound"
            raise CloudBuildParseError(message)
        self._depth += 1
        try:
            return self._compose_occurrence(parent, index)
        finally:
            self._depth -= 1

    def _compose_occurrence(self, parent: Node | None, index: int) -> Node | None:
        event: object = self.peek_event()  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType] -- PyYAML event boundary.
        if isinstance(event, AliasEvent):
            node = copy(super().compose_node(parent, index))
            if node is not None:
                if node.end_mark is None:
                    message = "Recursive YAML alias has no finite configuration"
                    raise CloudBuildParseError(message)
                node.start_mark = event.start_mark  # pyright: ignore[reportAny] -- PyYAML alias event mark boundary.
                node.end_mark = event.end_mark  # pyright: ignore[reportAny] -- PyYAML alias event mark boundary.
            return node
        return super().compose_node(parent, index)


def compose_documents(source: str) -> list[Node | None]:
    documents: list[Node | None] = list(yaml.compose_all(source, Loader=_UseSiteLoader))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType] -- PyYAML source node boundary.
    remaining = _MAX_YAML_NODES
    for document in documents:
        remaining = _check_expansion(document, remaining)
    return documents


def _check_expansion(node: Node | None, remaining: int) -> int:
    # Shared aliases remain small in memory, but constructors/validators still
    # visit each occurrence. Bound that expanded work before either runs.
    pending = [(node, 0)]
    while pending:
        current, depth = pending.pop()
        remaining -= 1
        if remaining < 0 or depth >= _MAX_YAML_DEPTH:
            message = "YAML expansion exceeds analysis node or depth bound"
            raise CloudBuildParseError(message)
        if isinstance(current, MappingNode):
            pending.extend((child, depth + 1) for pair in mapping_items(current) for child in pair)
        elif isinstance(current, SequenceNode):
            pending.extend((child, depth + 1) for child in sequence_items(current))
    return remaining


def mapping_fields(node: MappingNode) -> dict[str, Node]:
    return _mapping(node)


def scalar_text(node: Node | None) -> str | None:
    return _string(node)


def check_cloudbuild(path: Path, source: str, *, selected: bool = False) -> list[Finding]:
    if path.suffix.lower() not in {".yaml", ".yml"}:
        return []
    try:
        documents = compose_documents(source)
    except (yaml.YAMLError, CloudBuildParseError) as error:
        if selected:
            raise CloudBuildParseError(str(error)) from error
        return []
    findings: list[Finding] = []
    for document in documents:
        findings.extend(_document_findings(path, document, selected=selected))
    return findings


def _document_findings(path: Path, document: Node | None, *, selected: bool) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(document, MappingNode):
        return []
    if not selected and not _looks_like_build(document):
        return []
    root = _mapping(document)
    steps = root.get("steps")
    if not isinstance(steps, SequenceNode):
        return []
    entries = sequence_items(steps)
    if not entries or not all(isinstance(step, MappingNode) and "name" in _mapping(step) for step in entries):
        return []
    prior_ids: set[str] = set()
    for step in entries:
        if not isinstance(step, MappingNode):
            continue
        fields = _mapping(step)
        for node, message in _step_problems(fields, prior_ids):
            line = max(step.start_mark.line, node.start_mark.line) + 1
            findings.append(Finding(path, line, _CODE, message))
    return findings


def _looks_like_build(document: MappingNode) -> bool:
    for key, value in mapping_items(document):
        if _string(key) != "steps" or not isinstance(value, SequenceNode):
            continue
        for step in sequence_items(value):
            if isinstance(step, MappingNode) and any(_string(field) == "name" for field, _ in mapping_items(step)):
                return True
    return False


def _mapping(node: MappingNode, active: frozenset[int] = frozenset()) -> dict[str, Node]:
    if id(node) in active or len(active) >= _MAX_YAML_DEPTH:
        message = "Recursive or excessively nested YAML merge has no finite Cloud Build mapping"
        raise CloudBuildParseError(message)
    active |= {id(node)}
    result: dict[str, Node] = {}
    explicit: dict[str, Node] = {}
    for key, value in mapping_items(node):
        if isinstance(key, ScalarNode) and key.tag == "tag:yaml.org,2002:merge":
            merged = sequence_items(value) if isinstance(value, SequenceNode) else [value]
            for parent in reversed(merged):
                if not isinstance(parent, MappingNode):
                    message = "YAML merge source must be a mapping"
                    raise CloudBuildParseError(message)
                result.update(_mapping(parent, active))
            continue
        key_name = _string(key)
        if key_name is None:
            message = "Cloud Build mapping keys must be strings"
            raise CloudBuildParseError(message)
        if key_name in explicit:
            message = f"Duplicate YAML key {key_name!r} at line {key.start_mark.line + 1}"
            raise CloudBuildParseError(message)
        explicit[key_name] = value
    result.update(explicit)
    return result


def _string(node: Node | None) -> str | None:
    if not isinstance(node, ScalarNode) or node.tag != "tag:yaml.org,2002:str":
        return None
    value: object = node.value  # pyright: ignore[reportAny] -- PyYAML scalar boundary.
    return value if isinstance(value, str) else None


def _step_problems(fields: dict[str, Node], prior_ids: set[str]) -> Iterator[tuple[Node, str]]:
    step_id = _string(fields.get("id"))
    if step_id is not None and step_id in prior_ids:
        yield fields["id"], f"Cloud Build step ID {step_id!r} is duplicated; give each step a unique ID"
    wait_node = fields.get("waitFor")
    waits = _strings(wait_node)
    if waits is not None and isinstance(wait_node, SequenceNode):
        for dependency, node in zip(waits, sequence_items(wait_node), strict=True):
            if dependency == "-" and len(waits) != 1:
                yield node, "Cloud Build waitFor '-' must be the sole dependency"
            elif dependency != "-" and dependency not in prior_ids:
                yield node, f"Cloud Build waitFor {dependency!r} does not name a prior step; order dependencies first"
    if step_id is not None:
        prior_ids.add(step_id)
    script = fields.get("script")
    if script is not None and any(name in fields for name in ("args", "entrypoint")):
        yield script, "Cloud Build script cannot coexist with args or entrypoint; select one execution form"
    arg_node = fields.get("args")
    args = _strings(arg_node)
    entrypoint = _string(fields.get("entrypoint"))
    if (
        args is None
        or not isinstance(arg_node, SequenceNode)
        or entrypoint is None
        or entrypoint.rsplit("/", 1)[-1] not in _SHELLS
    ):
        return
    command_index = _command_index(args)
    if command_index is None:
        return
    if _has_build_substitution(args[command_index]):
        nodes = sequence_items(arg_node)
        yield (
            nodes[command_index],
            (
                "Cloud Build substitutes values into shell source; pass values through env or separate direct argv instead"
            ),
        )


def _strings(node: Node | None) -> list[str] | None:
    if not isinstance(node, SequenceNode):
        return None
    items = [_string(value) for value in sequence_items(node)]
    return [value for value in items if value is not None] if all(value is not None for value in items) else None


def _command_index(args: list[str]) -> int | None:
    index = 0
    while index < len(args):
        option = args[index]
        if _non_option(option):
            return None
        if option in _SHELL_LONG_VALUES:
            index += 2
            continue
        if option in _SHELL_LONG_FLAGS:
            index += 1
            continue
        flags = option[1:]
        if option.startswith("--") or any(flag not in "abefhkmnptuvxBCEHPTsioOcl" for flag in flags):
            return None
        index += 1 + sum(flag in "oO" for flag in flags)
        if option.startswith("-") and "c" in flags:
            return index if index < len(args) else None
    return None


def _non_option(option: str) -> bool:
    return option == "--" or not option.startswith(("-", "+")) or option in {"-", "+"}


def _has_build_substitution(source: str) -> bool:
    # $$ is Cloud Build's literal dollar escape. Shell quoting does not protect
    # a build-time substitution; script: uses environment variables instead.
    return any(
        match.group().lstrip("$").strip("{}") not in _SAFE_BUILTINS
        for match in _SUBSTITUTION.finditer(source.replace("$$", "\x00"))
    )
