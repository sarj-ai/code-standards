from __future__ import annotations

from io import BytesIO
import tarfile
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting.chart_schemas import validate_chart_schemas


if TYPE_CHECKING:
    from pathlib import Path


def _archive(files: tuple[tuple[str, bytes], ...]) -> bytes:
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, data in files:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, BytesIO(data))
    return output.getvalue()


def test_closed_schema_does_not_parse_unrelated_templated_json(tmp_path: Path) -> None:
    path = tmp_path / "chart.tgz"
    path.write_bytes(
        _archive(
            (
                ("chart/values.schema.json", b'{"$ref":"defs.json#/value"}'),
                ("chart/defs.json", b'{"value":{"type":"object"}}'),
                ("chart/templates/config.json", b"{{ .Values.config | toJson }}"),
            )
        )
    )
    validate_chart_schemas(path)


@pytest.mark.parametrize("reference", ["https://example.invalid/schema", "../missing.json", "/schema.json"])
def test_schema_reference_requires_local_archive_closure(tmp_path: Path, reference: str) -> None:
    path = tmp_path / "chart.tgz"
    path.write_bytes(_archive((("chart/values.schema.json", ('{"$ref":"' + reference + '"}').encode()),)))
    with pytest.raises(ValueError, match="reference"):
        validate_chart_schemas(path)


def test_packaged_subchart_cannot_hide_network_schema_reference(tmp_path: Path) -> None:
    dependency = _archive((("child/values.schema.json", b'{"$ref":"https://example.invalid/schema"}'),))
    path = tmp_path / "chart.tgz"
    path.write_bytes(_archive((("chart/charts/child.tgz", dependency),)))
    with pytest.raises(ValueError, match="network"):
        validate_chart_schemas(path)


def test_json_pointer_cannot_hide_network_reference_under_opaque_key(tmp_path: Path) -> None:
    path = tmp_path / "chart.tgz"
    path.write_bytes(
        _archive(
            (
                ("chart/values.schema.json", b'{"$ref":"defs.json#/opaque/value"}'),
                ("chart/defs.json", b'{"opaque":{"value":{"$ref":"https://example.invalid/remote"}}}'),
            )
        )
    )
    with pytest.raises(ValueError, match="network"):
        validate_chart_schemas(path)


def test_schema_network_base_cannot_reinterpret_hashed_local_file(tmp_path: Path) -> None:
    path = tmp_path / "chart.tgz"
    path.write_bytes(
        _archive(
            (
                (
                    "chart/values.schema.json",
                    b'{"$id":"https://example.invalid/base/","properties":{"value":{"$ref":"defs.json"}}}',
                ),
                ("chart/defs.json", b'{"type":"string"}'),
            )
        )
    )
    with pytest.raises(ValueError, match="base-changing"):
        validate_chart_schemas(path)


def test_duplicate_archive_files_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "chart.tgz"
    path.write_bytes(_archive((("chart/values.schema.json", b"{}"), ("chart/values.schema.json", b"{}"))))
    with pytest.raises(ValueError, match="duplicate"):
        validate_chart_schemas(path)


def test_nested_dependency_expansion_is_bounded(tmp_path: Path) -> None:
    content = _archive((("chart/values.schema.json", b"{}"),))
    for _ in range(10):
        content = _archive((("chart/charts/child.tgz", content),))
    path = tmp_path / "chart.tgz"
    path.write_bytes(content)
    with pytest.raises(ValueError, match="bound"):
        validate_chart_schemas(path)
