from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting.devops_schema import analyze_source_schemas


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("case_name", "source", "expected"),
    [
        pytest.param(
            "skaffold_direct_clean", "apiVersion: skaffold/v4beta7\nkind: Config\n", "clean", id="skaffold_direct_clean"
        ),
        pytest.param(
            "deploy_direct_clean",
            "apiVersion: deploy.cloud.google.com/v1\nkind: Target\nmetadata: {name: target}\n",
            "clean",
            id="deploy_direct_clean",
        ),
        pytest.param(
            "skaffold_direct_invalid",
            "apiVersion: skaffold/v4beta7\nkind: Config\nbuild: {artifacts: true}\n",
            "diagnostic",
            id="skaffold_direct_invalid",
        ),
        pytest.param(
            "deploy_direct_invalid",
            "apiVersion: deploy.cloud.google.com/v1\nkind: Target\nmetadata: {name: target}\nrequireApproval: 'true'\n",
            "diagnostic",
            id="deploy_direct_invalid",
        ),
        pytest.param(
            "skaffold_merge_clean",
            "<<: {apiVersion: skaffold/v4beta7, kind: Config}\n",
            "clean",
            id="skaffold_merge_clean",
        ),
        pytest.param(
            "skaffold_merge_invalid",
            "<<: {apiVersion: skaffold/v4beta7, kind: Config}\nbuild: {artifacts: true}\n",
            "diagnostic",
            id="skaffold_merge_invalid",
        ),
        pytest.param(
            "deploy_merge_clean",
            "<<: {apiVersion: deploy.cloud.google.com/v1, kind: Target}\nmetadata: {name: target}\n",
            "clean",
            id="deploy_merge_clean",
        ),
        pytest.param(
            "deploy_merge_invalid",
            "<<: {apiVersion: deploy.cloud.google.com/v1, kind: Target}\nmetadata: {name: target}\nrequireApproval: 9\n",
            "diagnostic",
            id="deploy_merge_invalid",
        ),
        pytest.param(
            "skaffold_nested_merge_clean",
            "<<: {<<: {apiVersion: skaffold/v4beta7, kind: Config}}\n",
            "clean",
            id="skaffold_nested_merge_clean",
        ),
        pytest.param(
            "skaffold_nested_merge_invalid",
            "<<: {<<: {apiVersion: skaffold/v4beta7, kind: Config}}\nbuild: {artifacts: true}\n",
            "diagnostic",
            id="skaffold_nested_merge_invalid",
        ),
        pytest.param(
            "deploy_nested_merge_invalid",
            "<<: {<<: {apiVersion: deploy.cloud.google.com/v1, kind: Target}}\nmetadata: {name: target}\nrequireApproval: []\n",
            "diagnostic",
            id="deploy_nested_merge_invalid",
        ),
        pytest.param(
            "merge_sequence_first_wins_clean",
            "<<: [{apiVersion: skaffold/v4beta7, kind: Config}, {apiVersion: skaffold/v999}]\n",
            "clean",
            id="merge_sequence_first_wins_clean",
        ),
        pytest.param(
            "merge_sequence_first_wins_failed",
            "<<: [{apiVersion: skaffold/v999, kind: Config}, {apiVersion: skaffold/v4beta7}]\n",
            "failed",
            id="merge_sequence_first_wins_failed",
        ),
        pytest.param(
            "merge_explicit_override_known",
            "<<: {apiVersion: skaffold/v999}\napiVersion: skaffold/v4beta7\nkind: Config\n",
            "clean",
            id="merge_explicit_override_known",
        ),
        pytest.param(
            "merge_explicit_override_other",
            "<<: {apiVersion: skaffold/v4beta7}\napiVersion: example/v1\n",
            "skip",
            id="merge_explicit_override_other",
        ),
        pytest.param(
            "merge_explicit_override_unsupported",
            "<<: {apiVersion: skaffold/v4beta7}\napiVersion: skaffold/v999\n",
            "failed",
            id="merge_explicit_override_unsupported",
        ),
        pytest.param(
            "merge_alias_sequence_clean",
            "<<: [&header {apiVersion: skaffold/v4beta7, kind: Config}, *header]\n",
            "clean",
            id="merge_alias_sequence_clean",
        ),
        pytest.param(
            "deploy_merged_unsupported_version",
            "<<: {apiVersion: deploy.cloud.google.com/v2, kind: Target}\nmetadata: {name: target}\n",
            "failed",
            id="deploy_merged_unsupported_version",
        ),
        pytest.param(
            "nested_unmerged_api_version",
            "metadata: {apiVersion: skaffold/v4beta7}\nbuild: {artifacts: true}\n",
            "skip",
            id="nested_unmerged_api_version",
        ),
        pytest.param(
            "comment_api_version",
            "# apiVersion: skaffold/v4beta7\nbuild: {artifacts: true}\n",
            "skip",
            id="comment_api_version",
        ),
        pytest.param(
            "scalar_api_version", 'description: "apiVersion: skaffold/v4beta7"\n', "skip", id="scalar_api_version"
        ),
        pytest.param(
            "sequence_document", "- {apiVersion: skaffold/v4beta7, kind: Config}\n", "skip", id="sequence_document"
        ),
        pytest.param(
            "quoted_merge_key_is_ordinary",
            "'<<': {apiVersion: skaffold/v4beta7}\n",
            "skip",
            id="quoted_merge_key_is_ordinary",
        ),
        pytest.param(
            "unrelated_duplicate", "apiVersion: example/v1\nname: x\nname: y\n", "skip", id="unrelated_duplicate"
        ),
        pytest.param(
            "unrelated_malformed_merge", "apiVersion: example/v1\n<<: 4\n", "skip", id="unrelated_malformed_merge"
        ),
        pytest.param(
            "direct_known_malformed_merge",
            "apiVersion: skaffold/v4beta7\nkind: Config\n<<: 4\n",
            "failed",
            id="direct_known_malformed_merge",
        ),
        pytest.param(
            "merged_known_duplicate_body",
            "<<: {apiVersion: skaffold/v4beta7, kind: Config}\nbuild: {}\nbuild: {}\n",
            "failed",
            id="merged_known_duplicate_body",
        ),
        pytest.param(
            "merged_known_duplicate_header",
            "<<: {apiVersion: skaffold/v4beta7, apiVersion: example/v1}\n",
            "failed",
            id="merged_known_duplicate_header",
        ),
        pytest.param(
            "duplicate_other_then_known",
            "apiVersion: example/v1\napiVersion: skaffold/v4beta7\nkind: Config\n",
            "failed",
            id="duplicate_other_then_known",
        ),
        pytest.param(
            "duplicate_known_then_other",
            "apiVersion: skaffold/v4beta7\nkind: Config\napiVersion: example/v1\n",
            "failed",
            id="duplicate_known_then_other",
        ),
        pytest.param(
            "duplicate_other_versions_only",
            "apiVersion: example/v1\napiVersion: other/v1\n",
            "skip",
            id="duplicate_other_versions_only",
        ),
        pytest.param(
            "multi_document",
            "apiVersion: skaffold/v4beta7\nkind: Config\n---\n<<: {apiVersion: deploy.cloud.google.com/v1, kind: Target}\nmetadata: {name: target}\n",
            "clean",
            id="multi_document",
        ),
        pytest.param(
            "skaffold_recursive_merge_selected",
            "apiVersion: skaffold/v4beta7\nloop: &loop {<<: *loop}\n",
            "failed",
            id="skaffold_recursive_merge_selected",
        ),
        pytest.param("recursive_merge_unrelated", "loop: &loop {<<: *loop}\n", "skip", id="recursive_merge_unrelated"),
        pytest.param(
            "skaffold_alias_unknown_selected",
            "apiVersion: skaffold/v4beta7\n<<: *missing\n",
            "failed",
            id="skaffold_alias_unknown_selected",
        ),
        pytest.param("alias_unknown_unrelated", "<<: *missing\n", "skip", id="alias_unknown_unrelated"),
    ],
)
def test_source_schema_discriminator_respects_yaml_semantics(
    tmp_path: Path, case_name: str, source: str, expected: str
) -> None:
    name = f"{case_name}.yaml"
    (tmp_path / name).write_text(source, encoding="utf-8")
    reports = analyze_source_schemas(root=tmp_path, paths=(name,))
    if expected == "skip":
        assert reports == ()
        return
    assert reports
    if expected == "failed":
        assert any(report.completion is Completion.FAILED for report in reports)
        assert all(not report.diagnostics for report in reports)
        return
    assert all(report.completion is Completion.COMPLETE for report in reports)
    findings = tuple(finding for report in reports for finding in report.diagnostics)
    if expected == "diagnostic":
        assert findings
        assert all(finding.rule_id in {"skaffold-schema", "clouddeploy-structure"} for finding in findings)
        assert all(finding.location.path == name for finding in findings)
    else:
        assert findings == ()
