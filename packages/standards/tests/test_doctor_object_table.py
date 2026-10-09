from __future__ import annotations

import json
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import doctor, manifest
from sarj_standards.libs.json_boundary import parse_json


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    "extra", [{}, {"nested": {}}, {"value": None}], ids=["minimal", "nested-metadata", "null-metadata"]
)
def test_doctor_accepts_actual_local_plugin_json_objects(tmp_path: Path, extra: dict[str, object]) -> None:
    name = "@sarj/eslint-plugin"
    version = manifest.eslint_peers()[name]
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {name: "file:plugin"}}))
    plugin = tmp_path / "plugin/package.json"
    plugin.parent.mkdir()
    plugin.write_text(json.dumps({"name": name, "version": version, **extra}))

    findings = [finding for finding in doctor.diagnose(tmp_path) if finding.id == "doctor.eslint.plugin"]

    assert len(findings) == 1
    assert findings[0].level is doctor.Level.OK


@pytest.mark.parametrize("kind", ["integer-key", "mixed-keys", "list", "null", "mapping-view"])
def test_doctor_does_not_attest_unproved_json_object_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    name = "@sarj/eslint-plugin"
    version = manifest.eslint_peers()[name]
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {name: "file:plugin"}}))
    plugin = tmp_path / "plugin/package.json"
    plugin.parent.mkdir()
    metadata = {"name": name, "version": version}
    source = json.dumps(metadata)
    plugin.write_text(source)
    values: dict[str, object] = {
        "integer-key": {1: "fixture"},
        "mixed-keys": {"name": name, "version": version, 1: None},
        "list": [],
        "null": None,
        "mapping-view": MappingProxyType(metadata),
    }

    def decoder(text: str) -> object:
        return values[kind] if text == source else parse_json(text)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- exercise the public doctor metadata boundary when the decoder returns an object outside its promised string-key contract.
        doctor, "parse_json", decoder
    )

    findings = [finding for finding in doctor.diagnose(tmp_path) if finding.id == "doctor.eslint.plugin-unverified"]

    assert len(findings) == 1
    assert findings[0].level is doctor.Level.WARN
