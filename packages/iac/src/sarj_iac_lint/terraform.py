from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from functools import lru_cache
import json
import re
from typing import TYPE_CHECKING, Final

from sarj_iac_lint import _hcl


if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path, PurePath


type JSONValue = str | _JSONNumber | bool | list[JSONValue] | dict[str, JSONValue] | None
type _JSONPath = tuple[str | int, ...]

_LABELS: Final = {
    "resource": 2,
    "data": 2,
    "ephemeral": 2,
    "action": 2,
    "variable": 1,
    "output": 1,
    "module": 1,
    "provider": 1,
    "check": 1,
    "locals": 0,
    "terraform": 0,
    "moved": 0,
    "removed": 0,
    "import": 0,
}
_LITERAL_ATTRIBUTES: Final = {
    "module": frozenset({"source", "version", "providers"}),
    "variable": frozenset({"default", "description"}),
    "provider": frozenset({"alias", "version"}),
    "output": frozenset({"description", "sensitive", "ephemeral"}),
}
_SPACE = re.compile(r"\s*")
_MAX_DEPTH = 128


@dataclass(frozen=True, slots=True)
class _JSONNumber:
    raw: str


def comment_texts(source: str) -> tuple[str, ...]:
    return _hcl.comment_texts(source)


def is_terraform(path: PurePath) -> bool:
    return path.name.endswith((".tf", ".tf.json"))


def is_terraform_override(path: PurePath) -> bool:
    return path.name in {"override.tf", "override.tf.json"} or path.name.endswith(("_override.tf", "_override.tf.json"))


@lru_cache(maxsize=128)
def terraform_blocks(path: PurePath, source: str) -> tuple[_hcl.Block, ...]:
    if path.name.endswith(".tf.json"):
        return _json_blocks(source)
    if not is_terraform(path):
        return ()
    parsed = _hcl.document_result(source)
    if isinstance(parsed, _hcl.RejectedDocument) or not _hcl.balanced_structure(source):
        reason = parsed.reason if isinstance(parsed, _hcl.RejectedDocument) else "unbalanced delimiters"
        message = f"Cannot analyze Terraform source {path}: {reason}"
        raise ValueError(message)
    _validate_attributes(parsed.root)
    return parsed.root.blocks


def terraform_document(path: PurePath, source: str) -> _hcl.Block:
    if path.name.endswith(".tf"):
        return _hcl.document(source)
    blocks = terraform_blocks(path, source)
    return _hcl.Block("", (), 0, 1, 1, max(len(source.splitlines()), 1), (), blocks)


def _validate_attributes(block: _hcl.Block) -> None:
    names: set[str] = set()
    for attribute in block.attributes:
        if attribute.name in names:
            message = f"Duplicate Terraform attribute {attribute.name}"
            raise ValueError(message)
        if not attribute.value.strip():
            message = f"Terraform attribute {attribute.name} requires a value"
            raise ValueError(message)
        names.add(attribute.name)
    for child in block.blocks:
        _validate_attributes(child)


def _unique_object(pairs: list[tuple[str, JSONValue]]) -> dict[str, JSONValue]:
    result: dict[str, JSONValue] = {}
    for key, value in pairs:
        if key in result:
            message = f"Duplicate Terraform JSON member: {key}"
            raise ValueError(message)
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    message = f"Non-JSON numeric constant: {value}"
    raise ValueError(message)


@dataclass(frozen=True, slots=True)
class _JSONPoint:
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class _JSONContext:
    source: str
    locations: dict[_JSONPath, _JSONPoint]
    newlines: tuple[int, ...]
    ends: dict[_JSONPath, int]

    def locate(self, value: JSONValue, start: int = 0, path: _JSONPath = ()) -> int:
        start = self.space(start)
        number = bisect_left(self.newlines, start)
        line_start = self.newlines[number - 1] + 1 if number else 0
        self.locations.setdefault(path, _JSONPoint(number + 1, start - line_start + 1))
        if isinstance(value, (dict, list)):
            cursor = self.space(start + 1)
            items = value.items() if isinstance(value, dict) else enumerate(value)
            for key, child in items:
                if isinstance(value, dict):
                    number = bisect_left(self.newlines, cursor)
                    line_start = self.newlines[number - 1] + 1 if number else 0
                    self.locations[*path, key] = _JSONPoint(number + 1, cursor - line_start + 1)
                    cursor = json.JSONDecoder().raw_decode(self.source, cursor)[1]
                    cursor = self.space(cursor) + 1
                cursor = self.space(self.locate(child, cursor, (*path, key)))
                if self.source[cursor : cursor + 1] == ",":
                    cursor = self.space(cursor + 1)
            end = cursor + 1
        else:
            end = json.JSONDecoder().raw_decode(self.source, start)[1]
        self.ends[path] = bisect_left(self.newlines, end) + 1
        return end

    def space(self, cursor: int) -> int:
        match = _SPACE.match(self.source, cursor)
        return match.end() if match is not None else cursor

    def point(self, path: _JSONPath) -> _JSONPoint:
        while path and path not in self.locations:
            path = path[:-1]
        return self.locations.get(path, _JSONPoint(1, 1))


def _json_blocks(source: str) -> tuple[_hcl.Block, ...]:
    payload: JSONValue = json.loads(  # pyright: ignore[reportAny] -- checked recursive JSON boundary; hooks preserve numeric lexemes and reject duplicate/non-JSON members.
        source,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
        parse_int=_JSONNumber,
        parse_float=_JSONNumber,
    )
    root = _mapping(payload)
    context = _JSONContext(source, {}, tuple(match.start() for match in re.finditer(r"\n", source)), {})
    try:
        context.locate(root)
    except (
        RecursionError
    ) as exc:  # sarj-noqa: SARJ585 -- Native JSON parse rejection normalizes unsupported nesting as ValueError.
        message = "Terraform JSON exceeds supported nesting"
        raise ValueError(message) from exc
    result: list[_hcl.Block] = []
    for kind, value in root.items():
        if kind == "//":
            continue
        if kind not in _LABELS:
            message = f"Unsupported Terraform JSON top-level block: {kind}"
            raise ValueError(message)
        for labels, body, path in _declarations(value, _LABELS[kind], (kind,)):
            result.append(_body(kind, labels, body, path, context, depth=0))
    return tuple(result)


def _mapping(value: JSONValue) -> dict[str, JSONValue]:
    if type(value) is not dict:
        message = "Terraform JSON block requires an object"
        raise ValueError(message)
    return value


def _declarations(
    value: JSONValue,
    remaining: int,
    path: _JSONPath,
    labels: tuple[str, ...] = (),
) -> Iterator[tuple[tuple[str, ...], dict[str, JSONValue], _JSONPath]]:
    if len(path) > _MAX_DEPTH:
        message = "Terraform JSON exceeds supported block nesting"
        raise ValueError(message)
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _declarations(item, remaining, (*path, index), labels)
    elif remaining:
        for label, item in _mapping(value).items():
            yield from _declarations(item, remaining - 1, (*path, label), (*labels, label))
    else:
        yield labels, _mapping(value), path


def _body(
    kind: str,
    labels: tuple[str, ...],
    values: dict[str, JSONValue],
    path: _JSONPath,
    context: _JSONContext,
    *,
    depth: int,
    literal: bool = False,
) -> _hcl.Block:
    if depth > _MAX_DEPTH:
        message = "Terraform JSON exceeds supported block nesting"
        raise ValueError(message)
    attributes: list[_hcl.Attribute] = []
    children: list[_hcl.Block] = []
    for name, value in values.items():
        if name == "//":
            continue
        location = (*path, name)
        if kind == "variable" and name == "validation" and not _is_block_body(value):
            message = "Terraform JSON variable validation requires a block object or array"
            raise ValueError(message)
        point = context.point(location)
        attributes.append(
            _hcl.Attribute(name, _attribute(kind, name, value, literal=literal), point.line, point.col, point.line)
        )
        # Provider schemas decide object versus nested-block meaning. Retain the expression and a structural projection;
        # rules must select known schema paths before interpreting a projection as a provider block.
        if _project_body(kind, name, value):
            label_count = _label_count(kind, name, value)
            for nested_labels, body, nested_path in _declarations(value, label_count, location):
                children.append(
                    _body(
                        name,
                        nested_labels,
                        body,
                        nested_path,
                        context,
                        depth=depth + 1,
                        literal=literal or kind == "terraform",
                    )
                )
    point = context.point(path)
    return _hcl.Block(
        kind,
        labels,
        depth,
        point.line,
        point.col,
        context.ends.get(path, point.line),
        tuple(attributes),
        tuple(children),
    )


def _label_count(kind: str, name: str, value: JSONValue) -> int:
    if name == "backend" and kind == "terraform":
        return 1
    if name == "dynamic" and isinstance(value, dict) and all(_is_block_body(item) for item in value.values()):
        return 1
    return 0


def _is_block_body(value: JSONValue) -> bool:
    return isinstance(value, dict) or (isinstance(value, list) and all(isinstance(item, dict) for item in value))


def _project_body(kind: str, name: str, value: JSONValue) -> bool:
    if kind == "variable" and name in _LITERAL_ATTRIBUTES["variable"]:
        return False
    return _is_block_body(value)


def _attribute(kind: str, name: str, value: JSONValue, *, literal: bool) -> str:
    if kind == "variable" and name == "type" and isinstance(value, str):
        return value
    if name == "depends_on" and kind in {"resource", "data", "ephemeral", "module", "output"}:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            message = "Terraform JSON depends_on must be an array of reference strings"
            raise ValueError(message)
        return "[" + ", ".join(str(item) for item in value) + "]"
    return json_expression(value, literal=literal or kind == "terraform" or name in _LITERAL_ATTRIBUTES.get(kind, ()))


def json_expression(value: JSONValue, *, literal: bool = False) -> str:
    match value:
        case _JSONNumber():
            return value.raw
        case dict():
            return (
                "{"
                + ", ".join(
                    f"{json_expression(key, literal=True)}: {json_expression(item, literal=literal)}"
                    for key, item in value.items()
                )
                + "}"
            )
        case list():
            return "[" + ", ".join(json_expression(item, literal=literal) for item in value) + "]"
        case _:
            pass
    if literal and isinstance(value, str):
        return json.dumps(value.replace("${", "$${").replace("%{", "%%{"), ensure_ascii=False)
    if not isinstance(value, str) or not any(marker in value for marker in ("${", "%{")):
        return json.dumps(value, ensure_ascii=False)
    delimiter = "SARJ_JSON_TEMPLATE"
    while delimiter in value.splitlines():
        delimiter += "_"
    template = f"<<{delimiter}\n{value}\n{delimiter}\n"
    if not _hcl.balanced_structure(template):
        message = "Malformed Terraform JSON expression template"
        raise ValueError(message)
    for expression in _hcl.template_expressions(template):
        if value == "${" + expression + "}":
            return expression
    return template


class TerraformSession:
    def __init__(self, sources: Mapping[Path, str]) -> None:
        self._modules: dict[Path, list[_hcl.Block]] = {}
        for path, source in sources.items():
            self._modules.setdefault(path.parent, []).extend(terraform_blocks(path, source))

    def blocks(self, path: Path) -> tuple[_hcl.Block, ...]:
        return tuple(self._modules.get(path.parent, ()))
