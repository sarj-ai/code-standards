from __future__ import annotations

from io import BytesIO
import json
import tarfile
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting.chart_schemas import validate_chart_schemas
from sarj_standards.libs.schema_boundary import HELM_SCHEMA_PROFILE, schema_references


if TYPE_CHECKING:
    from pathlib import Path


def _chart(tmp_path: Path, schema: dict[str, object], extra: tuple[tuple[str, bytes], ...] = ()) -> Path:
    path = tmp_path / "chart.tgz"
    with tarfile.open(path, "w:gz") as archive:
        for name, body in (("example/values.schema.json", json.dumps(schema).encode()), *extra):
            member = tarfile.TarInfo(name)
            member.size = len(body)
            archive.addfile(member, BytesIO(body))
    return path


@pytest.mark.parametrize(
    "dialect",
    ["https://json-schema.org/draft/2019-09/schema", "https://json-schema.org/draft/2020-12/schema"],
)
def test_native_supported_modern_dialects_are_admitted(tmp_path: Path, dialect: str) -> None:
    validate_chart_schemas(_chart(tmp_path, {"$schema": dialect, "type": "object"}))


@pytest.mark.parametrize(
    "name",
    [
        "example/assets/values.schema.json",
        "example/assets/charts/payload.tgz",
        "example/charts/_ignored/values.schema.json",
        "example/charts/.ignored/values.schema.json",
        "example/charts/child/docs/values.schema.json",
    ],
)
def test_native_inactive_chart_content_remains_data(tmp_path: Path, name: str) -> None:
    validate_chart_schemas(_chart(tmp_path, {}, ((name, b"arbitrary non-schema data"),)))


@pytest.mark.parametrize("keyword", ["$dynamicRef", "$recursiveRef"])
def test_default_native_reference_keywords_are_closed(tmp_path: Path, keyword: str) -> None:
    with pytest.raises(ValueError, match="network"):
        validate_chart_schemas(_chart(tmp_path, {keyword: "https://example.invalid/schema"}))


@pytest.mark.parametrize(
    "dialect",
    [
        "http://json-schema.org/draft-04/schema#",
        "http://json-schema.org/draft-06/schema#",
        "http://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft/2019-09/schema",
        "https://json-schema.org/draft/2020-12/schema",
    ],
)
def test_every_native_dependency_schema_is_closed(tmp_path: Path, dialect: str) -> None:
    schema: dict[str, object] = {
        "$schema": dialect,
        "dependencies": {"list": ["value"], "schema": {"$ref": "https://example.invalid/schema"}},
    }
    with pytest.raises(ValueError, match="network"):
        validate_chart_schemas(_chart(tmp_path, schema))


def test_native_profile_keeps_generic_schema_semantics_separate(tmp_path: Path) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$recursiveRef": "https://example.invalid/schema",
    }
    assert not schema_references(schema)
    assert schema_references(schema, profile=HELM_SCHEMA_PROFILE) == ("https://example.invalid/schema",)
    validate_chart_schemas(_chart(tmp_path, {"id": 2, "dependencies": {"list": ["$ref"]}}))
    validate_chart_schemas(
        _chart(
            tmp_path,
            {"$schema": "http://json-schema.org/draft-07/schema#", "$dynamicRef": "https://example.invalid/data"},
        )
    )
