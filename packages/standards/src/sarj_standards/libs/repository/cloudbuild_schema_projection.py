from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, JsonValue
import typer


app = typer.Typer(help="Project pinned Google discovery into the bundled Build-only field schema")


_SHA256 = "5dda7ec6030b1dfec239653bc9006548d5db520ee79b339b25e5465e2013a069"
_REQUIRED: Final = {"Build": ["steps"], "BuildStep": ["name"]}
type JsonSchema = dict[str, JsonValue]


class _Field(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    ref: str | None = Field(default=None, alias="$ref")
    identifier: str | None = Field(default=None, alias="id")
    kind: str | None = Field(default=None, alias="type")
    format: str | None = None
    description: str = ""
    properties: dict[str, _Field] = Field(default_factory=dict)
    items: _Field | None = None
    additional: _Field | None = Field(default=None, alias="additionalProperties")
    values: list[str] | None = Field(default=None, alias="enum")
    read_only: bool = Field(default=False, alias="readOnly")

    def as_schema(self) -> JsonSchema | bool:
        if self.read_only or self.description.startswith("Output only."):
            return False
        if self.ref is not None:
            return {"$ref": f"#/definitions/{self.ref}"}
        if self.format in {"int32", "int64"}:
            bits = 32 if self.format == "int32" else 64
            return {
                "anyOf": [
                    {"type": "integer", "minimum": -(2 ** (bits - 1)), "maximum": 2 ** (bits - 1) - 1},
                    {"type": "string", "format": self.format},
                ]
            }
        result: JsonSchema = self._object_schema() if self.kind == "object" else {"type": self.kind}
        if self.items is not None:
            result["items"] = self.items.as_schema()
        if self.values is not None:
            alternatives: JsonSchema = {
                "anyOf": [
                    {"type": "string", "enum": [*self.values]},
                    {"type": "integer", "minimum": -(2**31), "maximum": 2**31 - 1},
                ]
            }
            return alternatives
        if self.format is not None:
            result["format"] = self.format
        return result

    def _object_schema(self) -> JsonSchema:
        required = _REQUIRED.get(self.identifier, []) if self.identifier is not None else []
        properties: dict[str, JsonValue] = {}
        for key, definition in self.properties.items():
            field: JsonSchema | bool = definition.as_schema()
            if key not in required:
                field = {"if": {"type": "null"}, "else": field}
            properties[key] = field
            properties[re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()] = field
        result: JsonSchema = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False if self.additional is None else self.additional.as_schema(),
        }
        result["required"] = [*required]
        for name in required:
            required_schema = properties[name]
            if isinstance(required_schema, dict):
                required_schema["minItems" if name == "steps" else "minLength"] = 1
        return result


class _Discovery(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    schemas: dict[str, _Field]


def project_schema(source: Path) -> JsonSchema:
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != _SHA256:
        message = "Pinned upstream Cloud Build discovery digest does not match"
        raise ValueError(message)
    discovery = _Discovery.model_validate_json(payload)
    definitions = {name: field.as_schema() for name, field in discovery.schemas.items()}
    reachable: set[str] = set()
    pending = ["Build"]
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        pending.extend(_references(definitions[name]))
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$ref": "#/definitions/Build",
        "definitions": {name: definitions[name] for name in sorted(reachable)},
    }


def _references(value: JsonValue) -> list[str]:
    if isinstance(value, dict):
        reference = value.get("$ref")
        result = [reference.removeprefix("#/definitions/")] if isinstance(reference, str) else []
        for child in value.values():
            result.extend(_references(child))
        return result
    if isinstance(value, list):
        return [name for child in value for name in _references(child)]
    return []


@app.command()
def main(source: Path, output: Path) -> None:
    schema = project_schema(source)
    output.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    app()
