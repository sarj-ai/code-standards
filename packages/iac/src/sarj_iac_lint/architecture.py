from functools import lru_cache
from typing import TYPE_CHECKING

from jsonschema import Draft202012Validator

from sarj_iac_lint._hcl import comment_contents, physical_lines
from sarj_iac_lint.architecture_types import MinView, ModuleArchitecture, Replacement
from sarj_iac_lint.generate_architecture_types import annotation_schema
from sarj_iac_lint.json_boundary import JsonValue


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from jsonschema.protocols import Validator


SCHEMA_ID = "urn:sarj:calm:module-architecture:1"
_MARKER = " @architecture "
_ENUM_TOKEN_COUNT = 2


type CalmModuleDecorator = dict[str, JsonValue]


class ArchitectureAnnotationError(ValueError):
    pass


@lru_cache(maxsize=1)
def _validator() -> Validator:
    return Draft202012Validator(annotation_schema())


def parse_module_annotation(path: Path, source: str) -> ModuleArchitecture | None:
    marked = tuple(text for text in comment_contents(source) if "@architecture" in text.casefold())
    if not marked:
        return None
    lines = physical_lines(source)
    if path.name != "main.tf" or len(marked) != 1 or lines[1:2] != [""] or marked[0] != lines[0]:
        message = "Architecture metadata requires one first-line main.tf caption followed by a blank line"
        raise ArchitectureAnnotationError(message)
    caption, marker, fields = lines[0].removeprefix("# ").partition(_MARKER)
    values = fields.split(" ")
    if not lines[0].startswith("# ") or not marker or len(values) != _ENUM_TOKEN_COUNT:
        message = "Use # <purpose> @architecture <min_view> <replacement> with single spaces"
        raise ArchitectureAnnotationError(message)
    value = {"summary": caption, "min_view": values[0], "replacement": values[1]}
    if not _validator().is_valid(value):
        message = "Invalid architecture caption, visibility or replacement; see module-architecture.v1.schema.json"
        raise ArchitectureAnnotationError(message)
    return ModuleArchitecture(caption, MinView(values[0]), Replacement(values[1]))


def calm_decorator(
    annotation: ModuleArchitecture, *, unique_id: str, target: str, applies_to: Sequence[str]
) -> CalmModuleDecorator:
    value = {"summary": annotation.summary, "min_view": annotation.min_view, "replacement": annotation.replacement}
    if not _validator().is_valid(value):
        message = "Invalid architecture data; see module-architecture.v1.schema.json"
        raise ArchitectureAnnotationError(message)
    if not unique_id or not target or not applies_to or any(not item for item in applies_to):
        message = "CALM decoration requires an id, target and nonempty element ids"
        raise ArchitectureAnnotationError(message)
    return {
        "$schema": SCHEMA_ID,
        "unique-id": unique_id,
        "type": "sarj-module-architecture",
        "target": [target],
        "applies-to": list(applies_to),
        "data": value,
    }
