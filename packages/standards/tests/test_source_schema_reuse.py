from __future__ import annotations

import hashlib
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting import devops_schema


if TYPE_CHECKING:
    from collections.abc import Callable

    from sarj_standards.libs.diagnostics import ToolReport

_VALID = "apiVersion: skaffold/v4beta7\nkind: Config\nmetadata: {name: example}\n"
_INVALID = "apiVersion: skaffold/v4beta7\nkind: Config\nbuild: {artifacts: true}\n"
_SCHEMA_NAME = "skaffold-v4beta7.json"


@pytest.fixture
def schema_reads(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    read = Path.read_bytes
    paths: list[Path] = []

    def counting_read(path: Path) -> bytes:
        if path.name == _SCHEMA_NAME:
            paths.append(path)
        return read(path)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept the real schema I/O boundary; an injected loader would not verify reuse of the packaged artifact.
        Path, "read_bytes", counting_read
    )
    return paths


def _reports(root: Path, sources: tuple[str, ...]) -> tuple[ToolReport, ...]:
    paths: list[str] = []
    for index, source in enumerate(sources):
        path = f"skaffold-{index}.yaml"
        (root / path).write_text(source, encoding="utf-8")
        paths.append(path)
    return devops_schema.analyze_source_schemas(root=root, paths=tuple(paths))


@pytest.mark.parametrize("count", [2, 20])
def test_source_schema_is_reused_within_one_analysis(tmp_path: Path, schema_reads: list[Path], count: int) -> None:
    reports = _reports(tmp_path, (_VALID,) * count)
    assert len(reports) == count
    assert all(report.completion is Completion.COMPLETE and not report.diagnostics for report in reports)
    assert len(schema_reads) == 1


def test_mixed_diagnostics_keep_document_locations(tmp_path: Path, schema_reads: list[Path]) -> None:
    reports = _reports(tmp_path, (_VALID, _INVALID, _VALID, _INVALID))
    assert len(reports) == 4
    assert all(report.completion is Completion.COMPLETE for report in reports)
    assert not reports[0].diagnostics
    assert not reports[2].diagnostics
    for index in (1, 3):
        diagnostic = reports[index].diagnostics[0]
        assert diagnostic.location.path == f"skaffold-{index}.yaml"
        assert diagnostic.location.position is not None
        assert diagnostic.location.position.line == 2
    assert len(schema_reads) == 1


def test_multiple_documents_share_verified_schema(tmp_path: Path, schema_reads: list[Path]) -> None:
    reports = _reports(tmp_path, (_VALID + "---\n" + _INVALID,))
    assert len(reports) == 2
    assert not reports[0].diagnostics
    assert reports[1].diagnostics[0].location.position is not None
    assert reports[1].diagnostics[0].location.position.line == 6
    assert len(schema_reads) == 1


def test_new_analysis_rechecks_the_pinned_schema(tmp_path: Path, schema_reads: list[Path]) -> None:
    first = _reports(tmp_path, (_VALID, _INVALID))
    second = _reports(tmp_path, (_VALID, _INVALID))
    assert second == first
    assert len(schema_reads) == 2


def test_new_analysis_validates_changed_configuration(tmp_path: Path, schema_reads: list[Path]) -> None:
    first = _reports(tmp_path, (_VALID,))
    second = _reports(tmp_path, (_INVALID,))
    assert not first[0].diagnostics
    assert second[0].diagnostics
    assert len(schema_reads) == 2


def test_removed_schema_artifact_fails_a_new_analysis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    original = files("sarj_standards").joinpath("configs", "schemas", _SCHEMA_NAME).read_bytes()
    schema = schema_dir / _SCHEMA_NAME
    schema.write_bytes(original)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- replace the installed artifact location to test deletion between analyses without mutating the real installation or bypassing its loader.
        devops_schema, "_SCHEMAS", schema_dir
    )
    first = _reports(tmp_path, (_VALID,))
    assert first[0].completion is Completion.COMPLETE
    schema.unlink()
    removed = _reports(tmp_path, (_VALID, _VALID))
    assert all(report.completion is Completion.FAILED for report in removed)
    schema.write_bytes(original)
    assert _reports(tmp_path, (_VALID,)) == first


@pytest.mark.parametrize("change", [b" ", b"{}", b"not-json"])
def test_changed_schema_artifact_is_not_reused_between_analyses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: bytes
) -> None:
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    original = files("sarj_standards").joinpath("configs", "schemas", _SCHEMA_NAME).read_bytes()
    schema = schema_dir / _SCHEMA_NAME
    schema.write_bytes(original)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- emulate replacement of the installed artifact without mutating the installation; retain the real load and hash checks.
        devops_schema, "_SCHEMAS", schema_dir
    )
    first = _reports(tmp_path, (_VALID, _VALID))
    assert all(report.completion is Completion.COMPLETE for report in first)
    schema.write_bytes(original + change)
    changed = _reports(tmp_path, (_VALID, _VALID))
    assert all(report.completion is Completion.FAILED for report in changed)
    assert all("digest does not match" in report.issues[0].message for report in changed)
    schema.write_bytes(original)
    assert _reports(tmp_path, (_VALID, _VALID)) == first


@pytest.mark.parametrize("payload", [b"{", b"[]", b"null"])
def test_schema_load_failures_are_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, schema_reads: list[Path], payload: bytes
) -> None:
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    (schema_dir / _SCHEMA_NAME).write_bytes(payload)
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- emulate replacement of the installed artifact without mutating the installation; retain the real load and hash checks.
        devops_schema, "_SCHEMAS", schema_dir
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- admit a pinned malformed fixture through the digest boundary to exercise the unchanged parser failure and retry behavior.
        devops_schema, "_SKAFFOLD_SHA256", hashlib.sha256(payload).hexdigest()
    )
    reports = _reports(tmp_path, (_VALID, _VALID))
    assert all(report.completion is Completion.FAILED for report in reports)
    assert len(schema_reads) == 2


def test_transient_schema_read_failure_can_recover_in_same_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read: Callable[[Path], bytes] = Path.read_bytes
    attempts = 0

    def transient_read(path: Path) -> bytes:
        nonlocal attempts
        if path.name == _SCHEMA_NAME:
            attempts += 1
            if attempts == 1:
                message = "fixture schema read unavailable"
                raise OSError(message)
        return read(path)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- transient failure at the actual artifact read boundary must recover; injecting a preloaded schema would bypass the behavior.
        Path, "read_bytes", transient_read
    )
    reports = _reports(tmp_path, (_VALID,) * 3)
    assert reports[0].completion is Completion.FAILED
    assert all(report.completion is Completion.COMPLETE for report in reports[1:])
    assert attempts == 2


@pytest.mark.parametrize(
    "source",
    [
        "apiVersion: skaffold/v4beta8\nkind: Config\n",
        "apiVersion: deploy.cloud.google.com/v2\nkind: Target\n",
        "apiVersion: deploy.cloud.google.com/v1\nkind: Unknown\n",
    ],
)
def test_unknown_contracts_do_not_reuse_skaffold_validator(
    tmp_path: Path, schema_reads: list[Path], source: str
) -> None:
    reports = _reports(tmp_path, (_VALID, source, _VALID))
    assert reports[0].completion is Completion.COMPLETE
    assert reports[1].completion is Completion.FAILED
    assert reports[2].completion is Completion.COMPLETE
    assert len(schema_reads) == 1


@pytest.mark.parametrize(
    "source",
    [
        "apiVersion: skaffold/v4beta7\nkind: Config\nkind: Config\n",
        "apiVersion: skaffold/v4beta7\nkind: Config\nmetadata: {name: x, name: y}\n",
        "apiVersion: skaffold/v4beta7\nkind: Config\nunknown: &loop [*loop]\n",
    ],
)
def test_cached_validator_preserves_per_document_admission(
    tmp_path: Path, schema_reads: list[Path], source: str
) -> None:
    reports = _reports(tmp_path, (_VALID, source, _VALID))
    assert reports[0].completion is Completion.COMPLETE
    assert reports[1].completion is Completion.FAILED
    assert reports[2].completion is Completion.COMPLETE
    assert len(schema_reads) == 1


def test_unrelated_and_clouddeploy_documents_need_no_skaffold_schema(tmp_path: Path, schema_reads: list[Path]) -> None:
    sources = (
        "apiVersion: v1\nkind: ConfigMap\n",
        "apiVersion: deploy.cloud.google.com/v1\nkind: Target\nmetadata: {name: target}\n",
        "apiVersion: deploy.cloud.google.com/v1\nkind: DeliveryPipeline\nmetadata: {name: pipeline}\n",
        "apiVersion: deploy.cloud.google.com/v1\nkind: CustomTargetType\nmetadata: {name: custom}\n",
    )
    reports = _reports(tmp_path, sources)
    assert len(reports) == 3
    assert all(report.completion is Completion.COMPLETE and not report.diagnostics for report in reports)
    assert schema_reads == []
