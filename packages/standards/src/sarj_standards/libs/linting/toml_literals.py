from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
import re
import tomllib

from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


type TomlValuePath = tuple[str | int, ...]
TOML_STRING_OR_COMMENT_RE = re.compile(
    r"#[^\n]*|\"\"\"(?:\\.|(?!\"\"\")[^\\])*\"{3,5}|'''(?:(?!''').)*'{3,5}|\"(?:\\.|[^\"\\])*\"|'[^'\n]*'",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class TomlSource:
    document: Mapping[str, object]
    string_lines: Mapping[TomlValuePath, int]


class TomlStringLocationError(ValueError):
    """A native string value has no verified location in the original source."""


def parse_toml_string_lines(source: str) -> TomlSource:
    original: Mapping[str, object] = tomllib.loads(source)
    contents = _string_contents(original)
    prefix = "__sarj_source_span_"
    while any(prefix in value for value in contents):
        prefix += "x"
    spans: dict[str, tuple[int, int]] = {}
    for match in TOML_STRING_OR_COMMENT_RE.finditer(source):
        if not match.group().startswith("#"):
            spans[f"{prefix}{len(spans)}__"] = (match.start(), match.end())
    try:
        # Native parsing classifies candidates as keys or values; keys stay untouched in the final projection.
        all_marked: Mapping[str, object] = tomllib.loads(_replace_literals(source, spans, set(spans)))
        selected = _value_markers(all_marked, spans)
        marked: Mapping[str, object] = tomllib.loads(_replace_literals(source, spans, selected))
    except tomllib.TOMLDecodeError as error:
        msg = "TOML literal candidates do not preserve native syntax"
        raise TomlStringLocationError(msg) from error
    newline_offsets = [index for index, character in enumerate(source) if character == "\n"]
    return TomlSource(original, _verify_values(original, marked, spans, newline_offsets))


def _string_contents(document: Mapping[str, object]) -> list[str]:
    pending: list[object] = [document]
    strings: list[str] = []
    while pending:
        value = pending.pop()
        if is_object_mapping(value):
            strings.extend(key for key in value if isinstance(key, str))
            pending.extend(value.values())
        elif is_object_list(value):
            pending.extend(value)
        elif isinstance(value, str):
            strings.append(value)
    return strings


def _replace_literals(source: str, spans: Mapping[str, tuple[int, int]], selected: set[str]) -> str:
    chunks: list[str] = []
    cursor = 0
    for marker, (start, end) in spans.items():
        if marker in selected:
            chunks.extend((source[cursor:start], json.dumps(marker)))
            cursor = end
    chunks.append(source[cursor:])
    return "".join(chunks)


def _value_markers(document: Mapping[str, object], spans: Mapping[str, tuple[int, int]]) -> set[str]:
    pending: list[object] = [document]
    selected: set[str] = set()
    while pending:
        value = pending.pop()
        if is_object_mapping(value):
            pending.extend(value.values())
        elif is_object_list(value):
            pending.extend(value)
        elif isinstance(value, str) and value in spans:
            selected.add(value)
    return selected


def _verify_values(
    original: Mapping[str, object],
    marked: Mapping[str, object],
    spans: Mapping[str, tuple[int, int]],
    newline_offsets: list[int],
) -> dict[TomlValuePath, int]:
    pending: list[tuple[object, object, TomlValuePath]] = [(original, marked, ())]
    lines: dict[TomlValuePath, int] = {}
    while pending:
        left, right, path = pending.pop()
        children = _paired_children(left, right, path)
        if children is not None:
            pending.extend(children)
            continue
        if isinstance(left, str):
            if not isinstance(right, str) or right not in spans:
                msg = "TOML string value has no native-verified source location"
                raise TomlStringLocationError(msg)
            lines[path] = bisect_right(newline_offsets, spans[right][0]) + 1
        elif type(left) is not type(right) or not (
            left == right
            or (isinstance(left, float) and isinstance(right, float) and math.isnan(left) and math.isnan(right))
        ):
            msg = "TOML string attribution changes a native non-string value"
            raise TomlStringLocationError(msg)
    return lines


def _paired_children(
    left: object, right: object, path: TomlValuePath
) -> list[tuple[object, object, TomlValuePath]] | None:
    if is_object_mapping(left):
        if not is_object_mapping(right) or left.keys() != right.keys():
            msg = "TOML string attribution changes native key identity"
            raise TomlStringLocationError(msg)
        children: list[tuple[object, object, TomlValuePath]] = []
        for key, value in left.items():
            if not isinstance(key, str):
                msg = "native TOML keys must be strings"
                raise TomlStringLocationError(msg)
            children.append((value, right[key], (*path, key)))
        return children
    if is_object_list(left):
        if not is_object_list(right) or len(left) != len(right):
            msg = "TOML string attribution changes native array shape"
            raise TomlStringLocationError(msg)
        return [(a, b, (*path, index)) for index, (a, b) in enumerate(zip(left, right, strict=True))]
    return None
