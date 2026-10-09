from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting.devops_source import analyze_sources
from sarj_standards.libs.linting.external import ProcessOutput


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


@pytest.mark.parametrize("tool", ["terraform", "tflint"])
@pytest.mark.parametrize("mode", ["clean", "malformed", "untrusted"])
@pytest.mark.parametrize(
    "paths",
    [
        ("a/main.tf", "b/main.tf"),
        ("a/main.tf", "b/main.tf", "b/extra.tf.json"),
        ("main.tf", "nested/main.tf", "third/main.tf"),
        ("a/main.tf", "a/extra.tf.json"),
        (),
    ],
    ids=["two-projects", "mixed-hcl-json", "root-and-nested", "one-project", "empty-scope"],
)
def test_native_project_reports_count_only_selected_project_inputs(
    tmp_path: Path, tool: str, mode: str, paths: tuple[str, ...]
) -> None:
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n" if name.endswith(".json") else "terraform {}\n")

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path or cwd in {path.parent for path in tmp_path.rglob("*.tf")}
        if "version" in argv:
            return ProcessOutput(0, "Terraform v1.15.8", "")
        if "--version" in argv:
            return ProcessOutput(0, "TFLint version 0.63.1\nruleset.google (0.39.0)", "")
        if "fmt" in argv:
            return ProcessOutput(0, "", "")
        if mode == "malformed":
            return ProcessOutput(0, "{", "")
        payload = (
            '{"format_version":"1.0","valid":true,"error_count":0,"diagnostics":[]}'
            if "validate" in argv
            else '{"errors":[],"issues":[]}'
        )
        return ProcessOutput(0, payload, "")

    reports = analyze_sources(
        root=tmp_path,
        paths=paths,
        selected=frozenset({tool}),
        trust_repository_code=mode != "untrusted",
        runner=runner,
    )
    if not paths:
        assert reports == ()
        return
    project_counts = [
        sum((tmp_path / name).parent == project for name in paths)
        for project in sorted({(tmp_path / name).parent for name in paths})
    ]
    expected = (
        [sum(name.endswith(".tf") for name in paths), *project_counts]
        if tool == "terraform"
        else [len(paths)]
        if mode == "untrusted"
        else project_counts
    )
    assert [report.file_count for report in reports] == expected


def test_terraform_formatter_failure_counts_only_submitted_hcl_inputs(tmp_path: Path) -> None:
    hcl = tmp_path / "main.tf"
    json_input = tmp_path / "extra.tf.json"
    hcl.write_text("terraform {}\n")
    json_input.write_text("{}\n")
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        calls.append(tuple(argv))
        if "version" in argv:
            return ProcessOutput(0, "Terraform v1.15.8", "")
        assert tuple(argv) == ("terraform", "fmt", "-check", "-list=true", str(hcl))
        return ProcessOutput(9, "", "formatter failed")

    formatter, validation = analyze_sources(
        root=tmp_path,
        paths=(hcl.name, json_input.name),
        selected=frozenset({"terraform"}),
        runner=runner,
    )
    assert formatter.name == "terraform-fmt"
    assert formatter.completion is Completion.FAILED
    assert formatter.file_count == 1
    assert validation.file_count == 2
    assert all(str(json_input) not in argv for argv in calls)
