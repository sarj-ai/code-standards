from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting import cloudbuild_schema, devops_schema


if TYPE_CHECKING:
    from sarj_standards.libs.diagnostics import ToolReport


def _reports(tmp_path: Path, source: str, name: str = "cloudbuild.yaml") -> tuple[ToolReport, ...]:
    (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / name).write_bytes(source.encode("utf-8"))
    return devops_schema.analyze_source_schemas(root=tmp_path, paths=(name,))


@pytest.mark.parametrize(
    "source",
    [
        "steps:\n- name: builder\n  args: [build, '${_IMAGE}']\noptions:\n  diskSizeGb: 100\n  logging: CLOUD_LOGGING_ONLY\n",
        "steps:\n- name: builder\n  env: ['KEY=on']\n  allowFailure: false\n  automapSubstitutions: true\noptions:\n  diskSizeGb: '100'\n",
        "steps:\n- name: builder\n  timeout: 1.500s\ntimeout: 1200s\nsubstitutions: {_IMAGE: value}\n",
        "steps:\n- name: builder\navailableSecrets:\n  secretManager:\n  - versionName: projects/$PROJECT_ID/secrets/key/versions/latest\n    env: KEY\n",
        "steps:\n- name: builder\nartifacts:\n  pythonPackages:\n  - repository: https://example.invalid/python\n    paths: ['dist/*']\n",
        "steps:\n- name: builder\n  allow_failure: false\noptions:\n  disk_size_gb: '100'\n  logging: 2\nsubstitutions: {_IMAGE_NAME: image}\n",
        "steps:\n- name: builder\n  args: null\noptions:\n  logStreamingOption: null\n",
        "steps:\n- name: builder\n  allowExitCodes: ['2']\n",
        "steps:\n- name: builder\noptions:\n  diskSizeGb: '1e3'\n",
        "steps:\n- name: builder\n  allowExitCodes: ['1.0']\n",
        "steps:\n- name: builder\ntimeout: 315576000000.999999999s\n",
    ],
    ids=(
        "integer-and-enum",
        "quoted-int64-and-booleans",
        "durations-and-substitution",
        "secret-manager",
        "artifacts",
        "sdk-field-aliases",
        "unset-fields",
        "quoted-int32",
        "quoted-exponent",
        "whole-decimal-integer",
        "duration-wire-boundary",
    ),
)
def test_upstream_build_fields_accept_supported_source_forms(tmp_path: Path, source: str) -> None:
    (report,) = _reports(tmp_path, source)
    assert report.name == "cloudbuild-schema"
    assert report.completion is Completion.COMPLETE
    assert not report.diagnostics
    assert not report.issues


@pytest.mark.parametrize(
    "source",
    [
        "steps: {}\n",
        "steps: []\n",
        "steps:\n- args: [build]\n",
        "steps:\n- name: ''\n",
        "steps:\n- name: builder\n  argz: [build]\n",
        "steps:\n- name: builder\n  args: true\n",
        "steps:\n- name: builder\n  allowFailure: 'false'\n",
        "steps:\n- name: builder\noptions:\n  machineType: UNKNOWN_MACHINE\n",
        "steps:\n- name: builder\noptions:\n  diskSizeGb: true\n",
        "steps:\n- name: builder\noptions:\n  diskSizeGb: '9223372036854775808'\n",
        "steps:\n- name: builder\n  timeout: 20minutes\n",
        "steps:\n- name: builder\noptions:\n  pool: {nmae: worker-pool}\n",
        "steps:\n- name: builder\nsubstitutions: {_IMAGE: 42}\n",
        "steps:\n- name: builder\nstatus: SUCCESS\n",
        "steps:\n- name: builder\noptions:\n  logging: 2147483648\n",
        "steps:\n- name: builder\n  allowExitCodes: ['1.5']\n",
        "steps:\n- name: builder\ntimeout: 315576000001s\n",
    ],
    ids=(
        "steps-type",
        "empty-build",
        "missing-image",
        "empty-image",
        "step-typo",
        "args-type",
        "boolean-type",
        "enum",
        "bool-is-not-integer",
        "integer-overflow",
        "duration",
        "nested-typo",
        "map-value",
        "output-only",
        "enum-wire-overflow",
        "fractional-integer",
        "duration-wire-overflow",
    ),
)
def test_invalid_field_contracts_cannot_pass_as_valid_yaml(tmp_path: Path, source: str) -> None:
    (report,) = _reports(tmp_path, source)
    assert report.completion is Completion.COMPLETE
    assert report.diagnostics
    assert all(diagnostic.rule_id == "cloudbuild-schema" for diagnostic in report.diagnostics)
    assert not report.issues


def test_json_fields_share_the_same_contract_and_authored_location(tmp_path: Path) -> None:
    source = json.dumps({"steps": [{"name": "builder", "args": True}]}, indent=2)
    (report,) = _reports(tmp_path, source, "release.cloudbuild.json")
    (diagnostic,) = report.diagnostics
    assert diagnostic.location.position is not None
    assert diagnostic.location.position.line == 4
    assert diagnostic.location.path == "release.cloudbuild.json"


@pytest.mark.parametrize(
    ("source", "invalid"),
    [
        ('{"steps":[{"name":"builder"}],"options":{"diskSizeGb":1e3}}', False),
        ('{"steps":[{"name":"builder","args":[1e3]}]}', True),
    ],
    ids=("numeric-integer", "numeric-string-argument"),
)
def test_json_numbers_keep_json_types_instead_of_yaml_string_coercion(
    tmp_path: Path, source: str, *, invalid: bool
) -> None:
    (report,) = _reports(tmp_path, source, "cloudbuild.json")
    assert report.completion is Completion.COMPLETE
    assert bool(report.diagnostics) == invalid
    assert not report.issues


def test_json_diagnostic_byte_offset_preserves_unicode_and_crlf(tmp_path: Path) -> None:
    source = '{"substitutions":{"_LABEL":"🛠"},\r\n"steps":[{"name":"builder","args":true}]}'
    (report,) = _reports(tmp_path, source, "cloudbuild.json")
    (diagnostic,) = report.diagnostics
    assert diagnostic.location.position is not None
    assert diagnostic.location.position.byte_offset == source.encode().index(b"true")


@pytest.mark.parametrize(
    ("encoded", "invalid"),
    [
        ("ZXhhbXBsZQ==", False),
        ("ZXhhbXBsZQ", False),
        ("-_8=", False),
        ("-_8", False),
        ("ZXhh\nbXBsZQ==", False),
        ("not-base64!", True),
        ("A", True),
    ],
    ids=("standard-padded", "standard-unpadded", "url-padded", "url-unpadded", "wrapped", "alphabet", "length"),
)
def test_encrypted_byte_fields_follow_native_base64_forms(tmp_path: Path, encoded: str, *, invalid: bool) -> None:
    source = json.dumps(
        {
            "steps": [{"name": "builder"}],
            "secrets": [
                {
                    "kmsKeyName": "projects/$PROJECT_ID/locations/global/keyRings/build/cryptoKeys/key",
                    "secretEnv": {"PASSWORD": encoded},
                }
            ],
        }
    )
    (report,) = _reports(tmp_path, source, "cloudbuild.json")
    assert report.completion is Completion.COMPLETE
    assert bool(report.diagnostics) == invalid
    assert not report.issues


@pytest.mark.parametrize("source", ["steps: [", '{"steps": [], "steps": []}', '{"steps": [], "value": NaN}'])
def test_malformed_selected_json_is_coverage_failure(tmp_path: Path, source: str) -> None:
    (report,) = _reports(tmp_path, source, "cloudbuild.json")
    assert report.completion is Completion.FAILED
    assert report.issues
    assert not report.diagnostics


def test_upstream_schema_is_verified_once_per_analysis_and_reloaded_between_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read = Path.read_bytes
    reads: list[Path] = []

    def record(path: Path) -> bytes:
        if path.name == "google-build-v1-schema.json":
            reads.append(path)
        return read(path)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe the actual packaged artifact read; replacing the schema loader would not prove per-analysis verification.
        Path, "read_bytes", record
    )
    for index in range(2):
        (tmp_path / f"cloudbuild-{index}.yaml").write_text("steps:\n- name: builder\n")
    paths = ("cloudbuild-0.yaml", "cloudbuild-1.yaml")
    for _ in range(2):
        reports = devops_schema.analyze_source_schemas(root=tmp_path, paths=paths)
        assert len(reports) == 2
        assert all(report.completion is Completion.COMPLETE and not report.diagnostics for report in reports)
    assert len(reads) == 2


def test_modified_pinned_discovery_cannot_report_clean_coverage(tmp_path: Path) -> None:
    (tmp_path / "google-build-v1-schema.json").write_text("{}\n")
    with pytest.raises(ValueError, match="digest does not match"):
        cloudbuild_schema.build_schema(tmp_path)


def test_unrelated_step_lists_do_not_select_the_build_schema(tmp_path: Path) -> None:
    assert not _reports(tmp_path, "steps:\n- name: Check\n  run: echo ready\n", "task.yaml")


def test_build_directory_can_contain_other_native_configurations(tmp_path: Path) -> None:
    assert not _reports(tmp_path, "apiVersion: serving.knative.dev/v1\nkind: Service\n", "cloudbuild/service.yaml")


@pytest.mark.parametrize("source", ["", "[]", "true"])
def test_selected_non_object_cannot_silently_skip_validation(tmp_path: Path, source: str) -> None:
    (report,) = _reports(tmp_path, source)
    assert report.issues or report.diagnostics
