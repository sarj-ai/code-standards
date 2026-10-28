from __future__ import annotations

from dataclasses import replace
import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import devops, manifest
from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.devops_source import analyze_sources
from sarj_standards.libs.linting.devops_tools import TOOLS, checked_tool, invoke
from sarj_standards.libs.linting.external import ProcessOutput, analyze_external
from sarj_standards.libs.linting.policy import Policy
from sarj_standards.libs.typed_containers import is_object_list


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from pydantic import JsonValue


def _project(root: Path, files: tuple[str, ...]) -> None:
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=(),
        python_dest=".",
        typescript_dest=".",
        compose_version=TOOLS["docker"].version,
        compose_projects=(files,),
    )
    (root / manifest.MANIFEST_NAME).write_text(adopted.render())
    (root / "base.yaml").write_text("services:\n  app:\n    environment: {MODE: base}\n")
    (root / "override.yaml").write_text("services:\n  app:\n    image: alpine:3.22\n    environment: {MODE: overlay}\n")


@pytest.mark.parametrize(
    "selection", [("base.yaml",), ("override.yaml",), ("base.yaml", "override.yaml")], ids=("base", "overlay", "both")
)
def test_selecting_either_fragment_validates_the_complete_native_project(
    tmp_path: Path, selection: tuple[str, ...]
) -> None:
    _project(tmp_path, ("base.yaml", "override.yaml"))
    (report,) = analyze_sources(root=tmp_path, paths=selection, selected=frozenset({"compose"}))
    assert report.completion is Completion.COMPLETE
    assert report.version == TOOLS["docker"].version
    assert report.file_count == 2
    assert not report.diagnostics
    assert not report.issues


def test_final_merged_configuration_keeps_native_field_validation(tmp_path: Path) -> None:
    _project(tmp_path, ("base.yaml", "override.yaml"))
    (tmp_path / "override.yaml").write_text("services:\n  app:\n    unknown_field: value\n")
    (report,) = analyze_sources(root=tmp_path, paths=("override.yaml",), selected=frozenset({"compose"}))
    assert report.completion is Completion.FAILED
    assert report.file_count == 2
    assert report.issues


@pytest.mark.parametrize(
    ("files", "expected"),
    [(("base.yaml", "override.yaml"), "overlay"), (("override.yaml", "base.yaml"), "base")],
    ids=("overlay-last", "base-last"),
)
def test_overlay_order_is_the_declared_invocation_order(tmp_path: Path, files: tuple[str, ...], expected: str) -> None:
    _project(tmp_path, files)
    tool = checked_tool("docker", root=tmp_path)
    modes: list[list[object]] = []

    def observer(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        # Forward the SUT's commands to the actual attested Compose binary.
        output = invoke(tool, tuple(argv[1:]), root=cwd)
        if "config" in argv and output.returncode == 0:
            value = parse_json(output.stdout)
            for key in ("services", "app", "environment"):
                assert isinstance(value, dict)
                value = value[key]
            assert is_object_list(value)
            modes.append(value)
        return output

    (report,) = analyze_sources(root=tmp_path, paths=("base.yaml",), selected=frozenset({"compose"}), runner=observer)
    assert report.completion is Completion.COMPLETE
    assert modes == [[f"MODE={expected}"]]


def test_missing_project_member_fails_instead_of_validating_a_partial_project(tmp_path: Path) -> None:
    _project(tmp_path, ("base.yaml", "override.yaml"))
    (tmp_path / "override.yaml").unlink()
    (report,) = analyze_sources(root=tmp_path, paths=("base.yaml",), selected=frozenset({"compose"}))
    assert report.completion is Completion.FAILED


def test_unrelated_selection_does_not_run_declared_projects(tmp_path: Path) -> None:
    _project(tmp_path, ("base.yaml", "override.yaml"))
    (tmp_path / "unrelated.yaml").write_text("name: unrelated\n")
    assert not analyze_sources(root=tmp_path, paths=("unrelated.yaml",), selected=frozenset({"compose"}))
    assert devops.required_tools(tmp_path, (), capabilities=("compose",)) == ("docker",)


@pytest.mark.parametrize(
    "files",
    [[[]], [["../outside.yaml"]], [["/absolute.yaml"]], [["nested\\escape.yaml"]], ["base.yaml"]],
    ids=("empty", "parent", "absolute", "backslash", "not-a-group"),
)
def test_invalid_project_declarations_fail_at_the_manifest_boundary(tmp_path: Path, files: JsonValue) -> None:
    _project(tmp_path, ("base.yaml", "override.yaml"))
    path = tmp_path / manifest.MANIFEST_NAME
    source = path.read_text()
    start = source.index("compose_projects = ")
    source = source[:start] + "compose_projects = " + json.dumps(files) + "\n"
    path.write_text(source)
    with pytest.raises(ValueError, match=r"Compose|compose_projects"):
        manifest.load(tmp_path)


def test_original_scope_selects_declared_files_without_yaml_extensions(tmp_path: Path) -> None:
    _project(tmp_path, ("base.config", "extensionless"))
    (tmp_path / "base.yaml").rename(tmp_path / "base.config")
    (tmp_path / "override.yaml").rename(tmp_path / "extensionless")
    reports = analyze_external(("extensionless",), root=tmp_path, trust="safe", capabilities=frozenset({"compose"}))
    (report,) = (item for item in reports if item.name == "compose-static")
    assert report.completion is Completion.COMPLETE, report.issues
    assert report.file_count == 2


def test_full_repository_scope_cannot_skip_a_declared_project_with_all_inputs_missing(tmp_path: Path) -> None:
    _project(tmp_path, ("missing.base", "missing.overlay"))
    reports = analyze_external((".",), root=tmp_path, trust="safe", capabilities=frozenset({"compose"}))
    (report,) = (item for item in reports if item.name == "compose-static")
    assert report.completion is Completion.FAILED
    assert report.issues


def test_declared_conventional_base_is_not_validated_as_an_independent_fragment(tmp_path: Path) -> None:
    _project(tmp_path, ("compose.yaml", "override.yaml"))
    (tmp_path / "base.yaml").rename(tmp_path / "compose.yaml")
    (report,) = analyze_sources(root=tmp_path, paths=("compose.yaml", "override.yaml"), selected=frozenset({"compose"}))
    assert report.completion is Completion.COMPLETE
    assert report.file_count == 2


def test_directory_scope_preserves_explicit_project_path_exclusions(tmp_path: Path) -> None:
    _project(tmp_path, ("base.yaml", "override.yaml"))
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    adopted = replace(adopted, excluded_paths=("base.yaml", "override.yaml"))
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render())
    reports = analyze_external(
        (".",),
        root=tmp_path,
        trust="safe",
        capabilities=frozenset({"compose"}),
        policy=Policy.from_manifest(tmp_path, adopted),
    )
    assert not any(report.name == "compose-static" for report in reports)


@pytest.mark.parametrize("selection", [("base.yaml",), ("override.yaml",)], ids=("shared-base", "one-overlay"))
def test_shared_base_selects_all_dependent_projects_and_overlay_selects_its_project(
    tmp_path: Path, selection: tuple[str, ...]
) -> None:
    _project(tmp_path, ("base.yaml", "override.yaml"))
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    adopted = replace(adopted, compose_projects=(("base.yaml", "override.yaml"), ("base.yaml", "second.yaml")))
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render())
    (tmp_path / "second.yaml").write_text("services:\n  app:\n    image: alpine:3.22\n")
    reports = analyze_sources(root=tmp_path, paths=selection, selected=frozenset({"compose"}))
    assert len(reports) == (2 if selection == ("base.yaml",) else 1)
    assert all(report.completion is Completion.COMPLETE and report.file_count == 2 for report in reports)
