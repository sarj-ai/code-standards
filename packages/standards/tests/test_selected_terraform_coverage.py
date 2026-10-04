from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from sarj_standards import api
from sarj_standards.cli.main import main as cli_main
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def terraform_repository(tmp_path: Path) -> Path:
    tests = tmp_path / "iac" / "tests"
    tests.mkdir(parents=True)
    for index in range(4):
        (tests / f"routing-{index}.tftest.hcl").write_text(
            'override_module {\n  target = module.storage\n  outputs = { arn = "fixture-arn" }\n}\n'
            'run "routing" {\n  assert {\n    condition = module.storage.arn == "fixture-arn"\n'
            '    error_message = "ARN mismatch"\n  }\n}\n',
            encoding="utf-8",
        )
    subprocess.run(("git", "init", "-q"), cwd=tmp_path, check=True, capture_output=True, shell=False)
    subprocess.run(("git", "add", "iac"), cwd=tmp_path, check=True, capture_output=True, shell=False)
    return tmp_path


def test_python_only_cli_checks_all_explicit_files_without_implicit_terraform_coverage(
    terraform_repository: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = terraform_repository
    sources = root / "src"
    sources.mkdir()
    paths = [sources / f"owner_{index}.py" for index in range(420)]
    for path in paths:
        path.write_text("value = 1\n", encoding="utf-8")

    status = cli_main(
        [
            "--root",
            str(root),
            "check",
            "--format",
            "json",
            "--rule",
            "python:prefer-native-string-check",
            *map(str, paths),
        ]
    )

    output = capsys.readouterr()
    report = parse_json(output.out)
    assert is_object_mapping(report)
    tools = report["tools"]
    assert is_object_list(tools)
    assert status == 0
    assert not output.err
    assert report["completion"] == "complete"
    assert report["coverage"] == []
    assert len(tools) == 1
    tool = tools[0]
    assert is_object_mapping(tool)
    assert (tool["name"], tool["fileCount"]) == ("sarj-python-lint", 420)


@pytest.mark.parametrize(
    "selected", [None, ("iac:no-mocked-terraform-test-oracle",)], ids=["whole-policy", "selected-iac"]
)
def test_policy_analysis_keeps_tracked_terraform_tests_outside_explicit_paths(
    terraform_repository: Path,
    selected: tuple[str, ...] | None,
) -> None:
    root = terraform_repository
    source = root / "owner.py"
    source.write_text("value = 1\n", encoding="utf-8")

    report = api.Standards(root).analyze(
        [str(source)] if selected is None else [], mode=api.AnalysisMode.CORPUS, rules=selected
    )

    assert report.completion is api.Completion.COMPLETE
    assert report.exit_code == 1
    assert [finding.location.path for finding in report.diagnostics if finding.code == "SARJ206"] == [
        f"iac/tests/routing-{index}.tftest.hcl" for index in range(4)
    ]
    assert [(tool.name, tool.file_count) for tool in report.tools if tool.name == "sarj-iac-lint"] == [
        ("sarj-iac-lint", 4)
    ]


@pytest.mark.parametrize(
    ("selection", "filename"),
    [
        ("python:prefer-native-string-check", "iac/tests/routing-0.tftest.hcl"),
        ("iac:no-mocked-terraform-test-oracle", "owner.py"),
    ],
    ids=["terraform-explicitly-selected-for-python", "python-explicitly-selected-for-iac"],
)
def test_explicit_wrong_file_type_remains_incomplete_coverage(
    terraform_repository: Path,
    selection: str,
    filename: str,
) -> None:
    root = terraform_repository
    (root / "owner.py").write_text("value = 1\n", encoding="utf-8")

    report = api.Standards(root).analyze([str(root / filename)], rules=(selection,))

    assert report.completion is api.Completion.PARTIAL
    assert report.exit_code == 2
    assert [(notice.reason, notice.file_count) for notice in report.coverage] == [
        ("no bundled analyzer accepts the selected file type", 1)
    ]


def test_raw_selected_iac_analysis_does_not_add_repository_tests(terraform_repository: Path) -> None:
    report = api.Standards(terraform_repository).analyze(
        [], mode=api.AnalysisMode.RAW, rules=("iac:no-mocked-terraform-test-oracle",)
    )

    assert report.completion is api.Completion.COMPLETE
    assert report.exit_code == 0
    assert report.tools == ()
