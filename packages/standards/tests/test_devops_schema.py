from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting.devops_schema import analyze_source_schemas


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_standards.libs.diagnostics import ToolReport


def _reports(tmp_path: Path, source: str, *, name: str = "skaffold.yaml") -> tuple[ToolReport, ...]:
    (tmp_path / name).write_text(source, encoding="utf-8")
    return analyze_source_schemas(root=tmp_path, paths=(name,))


def test_official_skaffold_schema_accepts_valid_minimal_config(tmp_path: Path) -> None:
    reports = _reports(tmp_path, "apiVersion: skaffold/v4beta7\nkind: Config\nmetadata:\n  name: example\n")
    assert len(reports) == 1
    assert reports[0].completion is Completion.COMPLETE
    assert reports[0].diagnostics == ()


def test_official_skaffold_schema_reports_source_field(tmp_path: Path) -> None:
    reports = _reports(tmp_path, "apiVersion: skaffold/v4beta7\nkind: Config\nbuild:\n  artifacts: true\n")
    assert reports[0].completion is Completion.COMPLETE
    assert reports[0].diagnostics[0].location.position is not None
    assert reports[0].diagnostics[0].location.position.line == 3


@pytest.mark.parametrize("version", ["skaffold/v4beta8", "deploy.cloud.google.com/v2"])
def test_unknown_schema_version_is_fatal_coverage(tmp_path: Path, version: str) -> None:
    reports = _reports(tmp_path, f"apiVersion: {version}\nkind: Config\n")
    assert reports[0].completion is Completion.FAILED
    assert reports[0].diagnostics == ()


@pytest.mark.parametrize(
    "source",
    [
        "apiVersion: [",
        "apiVersion: skaffold/v4beta7\nkind: Config\nkind: Config\n",
        "apiVersion: skaffold/v4beta7\nkind: Config\nmetadata: {name: x, name: y}\n",
    ],
)
def test_malformed_selected_config_is_fatal_coverage(tmp_path: Path, source: str) -> None:
    reports = _reports(tmp_path, source)
    assert reports[0].completion is Completion.FAILED
    assert reports[0].diagnostics == ()


def test_arbitrary_malformed_yaml_is_owned_by_yaml_engine(tmp_path: Path) -> None:
    assert _reports(tmp_path, "invalid: [", name="other.yaml") == ()


def test_clouddeploy_partial_contract_allows_future_fields(tmp_path: Path) -> None:
    reports = _reports(
        tmp_path,
        "apiVersion: deploy.cloud.google.com/v1\nkind: Target\nmetadata: {name: target}\nfutureField: {enabled: true}\nrequireApproval: true\n",
    )
    assert reports[0].completion is Completion.COMPLETE
    assert reports[0].diagnostics == ()


def test_clouddeploy_known_boolean_type_is_checked(tmp_path: Path) -> None:
    reports = _reports(
        tmp_path,
        "apiVersion: deploy.cloud.google.com/v1\nkind: Target\nmetadata: {name: target}\nrequireApproval: 'true'\n",
    )
    assert reports[0].diagnostics[0].location.position is not None
    assert reports[0].diagnostics[0].location.position.line == 3


def test_multi_document_contracts_each_receive_coverage(tmp_path: Path) -> None:
    reports = _reports(
        tmp_path,
        "apiVersion: skaffold/v4beta7\nkind: Config\n---\napiVersion: deploy.cloud.google.com/v1\nkind: DeliveryPipeline\nmetadata: {name: pipeline}\n",
    )
    assert len(reports) == 2
    assert all(report.completion is Completion.COMPLETE for report in reports)


def test_schema_alias_error_points_to_use_site(tmp_path: Path) -> None:
    reports = _reports(
        tmp_path,
        "apiVersion: deploy.cloud.google.com/v1\nkind: Target\nmetadata: {name: target}\nalias: &bad 'true'\nrequireApproval: *bad\n",
    )
    assert reports[0].diagnostics[0].location.position is not None
    assert reports[0].diagnostics[0].location.position.line == 4


def test_deep_schema_input_is_fatal_coverage(tmp_path: Path) -> None:
    reports = _reports(
        tmp_path, "apiVersion: skaffold/v4beta7\nkind: Config\nunknown: " + "[" * 70 + "0" + "]" * 70 + "\n"
    )
    assert reports[0].completion is Completion.FAILED
    assert reports[0].diagnostics == ()


@pytest.mark.parametrize(
    "header",
    [
        pytest.param("apiVersion: skaffold/v4beta7\nkind: Config\n", id="skaffold"),
        pytest.param(
            "apiVersion: deploy.cloud.google.com/v1\nkind: Target\nmetadata: {name: target}\n", id="clouddeploy"
        ),
    ],
)
@pytest.mark.parametrize("recursive", [pytest.param(False, id="amplified"), pytest.param(True, id="recursive")])
def test_schema_alias_expansion_fails_coverage_before_construction(
    tmp_path: Path, header: str, *, recursive: bool
) -> None:
    graph = "a0: &a0 [x]\n" + "".join(
        f"a{level}: &a{level} [{', '.join([f'*a{level - 1}'] * 5)}]\n" for level in range(1, 8)
    )
    reports = _reports(tmp_path, header + ("unknown: &loop [*loop]\n" if recursive else graph))
    assert len(reports) == 1
    assert reports[0].completion is Completion.FAILED
    assert reports[0].diagnostics == ()
    assert reports[0].issues[0].kind == "coverage-failure"
