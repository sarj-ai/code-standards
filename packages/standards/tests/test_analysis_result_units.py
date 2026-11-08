from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.diagnostics import Completion, ToolReport
from sarj_standards.libs.linting import devops_source, devops_tools, embedded_shell, result_cache
from sarj_standards.libs.linting.external import DEFAULT_EXECUTOR
from sarj_standards.libs.linting.result_cache import UnknownInputsError
from sarj_standards.libs.linting.terraform_inputs import project_inputs


if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SARJ_STANDARDS_RESULT_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("SARJ_STANDARDS_RESULT_CACHE_WRITE", "1")
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- editable test installs have no immutable engine record.
        result_cache, "_engine_identity", lambda: "engine"
    )
    root = tmp_path / "repository"
    root.mkdir()
    return root


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _workflow(command: str) -> str:
    return (
        "name: checks\n'on': push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
        f"      - shell: bash\n        run: |\n          {command}\n"
    )


def _logged_tools(root: Path, log: Path) -> embedded_shell.AttestedExecutables:
    def resolve(name: str) -> Path:
        real = devops_tools.checked_tool(name, root=root).executable
        assert real is not None
        wrapper = root.parent / f"logged-{name}"
        wrapper.write_text(f'#!/bin/sh\necho {name} >>"{log}"\nexec "{real}" "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        return wrapper

    return embedded_shell.AttestedExecutables(resolve)


def _embedded(root: Path, paths: list[Path], log: Path) -> tuple[ToolReport, ...]:
    return embedded_shell.analyze_sources(
        root=root,
        paths=[str(path) for path in paths],
        selected=frozenset({"shellcheck", "shfmt"}),
        executables=_logged_tools(root, log),
    )


def test_embedded_shell_reuses_unchanged_files_and_reruns_changed_ones(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = cache.parent / "tool.log"
    first = _write(cache, ".github/workflows/a.yml", _workflow("echo $value"))
    second = _write(cache, ".github/workflows/b.yml", _workflow('echo "$value"'))

    cold = _embedded(cache, [first, second], log)
    assert "embedded-shell reused 0 of 2 units" in capsys.readouterr().err
    log.unlink()

    warm = _embedded(cache, [first, second], log)
    assert warm == cold
    assert not log.exists()
    assert "embedded-shell reused 2 of 2 units" in capsys.readouterr().err

    _write(cache, ".github/workflows/b.yml", _workflow("echo $other"))
    changed = _embedded(cache, [first, second], log)
    assert "embedded-shell reused 1 of 2 units" in capsys.readouterr().err
    assert log.exists()
    assert changed[:2] == cold[:2]
    assert any(item.rule_id == "SC2086" for report in changed[2:] for item in report.diagnostics)


def test_embedded_shell_reruns_when_the_manifest_policy_changes(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = cache.parent / "tool.log"
    workflow = _write(cache, ".github/workflows/a.yml", _workflow("echo $value"))
    adopted = manifest.Manifest(version="8.190.0", configs=("ruff",), python_dest=".", typescript_dest=".")
    _write(cache, manifest.MANIFEST_NAME, adopted.render())
    _embedded(cache, [workflow], log)
    _write(cache, manifest.MANIFEST_NAME, replace(adopted, excluded_rules=("shellcheck:SC2086",)).render())

    _embedded(cache, [workflow], log)

    assert "embedded-shell reused 0 of 1 units" in capsys.readouterr().err.splitlines()[-1]


def test_read_only_runs_do_not_store_per_file_results(
    cache: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SARJ_STANDARDS_RESULT_CACHE_WRITE")
    log = cache.parent / "tool.log"
    workflow = _write(cache, ".github/workflows/a.yml", _workflow("echo $value"))

    _embedded(cache, [workflow], log)
    _embedded(cache, [workflow], log)

    assert capsys.readouterr().err.count("embedded-shell reused 0 of 1 units") == 2


def _terraform_project(root: Path) -> Path:
    project = root / "iac" / "stack"
    _write(
        root,
        "iac/stack/main.tf",
        'locals {\n  config_dir = "${path.module}/configs"\n}\n\n'
        'module "network" {\n  source = "../modules/network"\n}\n\n'
        'output "a" {\n  value = file("${local.config_dir}/a.yaml")\n}\n'
        'output "b" {\n  value = templatefile("${path.module}/b.tftpl", {})\n}\n',
    )
    _write(root, "iac/stack/configs/a.yaml", "a: 1\n")
    _write(root, "iac/stack/b.tftpl", '${file("${path.module}/nested.txt")}\n')
    _write(root, "iac/stack/nested.txt", "nested\n")
    _write(
        root,
        "iac/modules/network/main.tf",
        'output "c" {\n  value = file("${path.module}/../../../shared/c.json")\n}\n',
    )
    _write(root, "shared/c.json", "{}\n")
    _write(root, "unrelated/readme.md", "unrelated\n")
    return project


@pytest.mark.parametrize(
    "changed",
    [
        "iac/stack/main.tf",
        "iac/stack/configs/a.yaml",
        "iac/stack/nested.txt",
        "iac/modules/network/main.tf",
        "shared/c.json",
        "iac/stack/terraform.tfvars",
        "iac/stack/.terraform/modules/modules.json",
    ],
)
def test_terraform_inputs_cover_every_reachable_file(tmp_path: Path, changed: str) -> None:
    project = _terraform_project(tmp_path)
    before = project_inputs(tmp_path, project)

    _write(tmp_path, changed, "# changed\n" if changed.endswith((".tf", ".tfvars")) else '{"Modules": []}\n')

    assert project_inputs(tmp_path, project) != before


def test_terraform_inputs_ignore_unreachable_files(tmp_path: Path) -> None:
    project = _terraform_project(tmp_path)
    before = project_inputs(tmp_path, project)

    _write(tmp_path, "unrelated/readme.md", "changed\n")
    _write(tmp_path, "iac/other/main.tf", "# another root\n")

    assert project_inputs(tmp_path, project) == before


@pytest.mark.parametrize(
    "expression",
    [
        "file(var.path)",
        'file("${var.directory}/a.yaml")',
        "file(local.missing)",
        'file("${path.module}/../../../outside.txt")',
        'templatefile(abspath("x"), {})',
    ],
)
def test_terraform_inputs_are_unknown_for_unprovable_paths(tmp_path: Path, expression: str) -> None:
    project = tmp_path / "iac" / "stack"
    _write(tmp_path, "iac/stack/main.tf", f'output "a" {{\n  value = {expression}\n}}\n')

    with pytest.raises(UnknownInputsError):
        project_inputs(tmp_path, project)


def test_terraform_inputs_cover_a_computed_suffix_by_its_static_directory(tmp_path: Path) -> None:
    project = tmp_path / "iac" / "stack"
    _write(
        tmp_path,
        "iac/stack/main.tf",
        'output "a" {\n  value = [for name in fileset("${path.module}/scripts", "*") : '
        'file("${path.module}/scripts/${name}")]\n}\n',
    )
    _write(tmp_path, "iac/stack/scripts/one.sh", "echo one\n")
    before = project_inputs(tmp_path, project)

    _write(tmp_path, "iac/stack/scripts/two.sh", "echo two\n")

    assert project_inputs(tmp_path, project) != before


def test_terraform_projects_reuse_results_only_while_their_inputs_are_unchanged(
    cache: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _terraform_project(cache)
    paths = (project / "main.tf",)
    runs: list[str] = []

    def analyze() -> ToolReport:
        runs.append("terraform")
        return ToolReport("terraform", Completion.COMPLETE, file_count=1)

    def cached() -> ToolReport:
        outcomes: list[bool] = []
        report = devops_source.cached_project(
            "terraform-validate",
            cache,
            project,
            paths,
            DEFAULT_EXECUTOR,
            tools=(),
            outcomes=outcomes,
            compute=analyze,
        )
        result_cache.notice_outcomes("terraform-validate", outcomes)
        return report

    assert cached() == cached()
    assert runs == ["terraform"]
    _write(cache, "shared/c.json", '{"changed": true}\n')
    cached()
    assert runs == ["terraform", "terraform"]
    assert "terraform-validate reused 1 of 1 units" in capsys.readouterr().err


def test_unknown_terraform_inputs_always_run(cache: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = cache / "iac" / "stack"
    _write(cache, "iac/stack/main.tf", 'output "a" {\n  value = file(var.path)\n}\n')
    runs: list[str] = []

    def analyze() -> ToolReport:
        runs.append("terraform")
        return ToolReport("terraform", Completion.COMPLETE, file_count=1)

    for _ in range(2):
        devops_source.cached_project(
            "terraform-validate",
            cache,
            project,
            (project / "main.tf",),
            DEFAULT_EXECUTOR,
            tools=(),
            outcomes=[],
            compute=analyze,
        )

    assert runs == ["terraform", "terraform"]
    assert "fingerprint unavailable (UnknownInputsError)" in capsys.readouterr().err


def test_tool_locations_do_not_change_the_environment_identity() -> None:
    base = {"HOME": "/home/runner", "LANG": "C.UTF-8", "PATH": "/runner/env-1/bin:/usr/bin", "UV_CACHE_DIR": "/a"}
    moved = {**base, "PATH": "/runner/env-2/bin:/usr/bin", "UV_CACHE_DIR": "/b", "MISE_DATA_DIR": "/c"}

    assert result_cache.environment_parts(base) == result_cache.environment_parts(moved)
    assert result_cache.environment_parts(base) != result_cache.environment_parts({**base, "LANG": "ar_SA.UTF-8"})
