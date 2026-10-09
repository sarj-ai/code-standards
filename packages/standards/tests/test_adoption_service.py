from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import launcher, lifecycle, manifest
from sarj_standards.libs.adoption.service import (
    InitFailure,
    SyncOutcome,
    apply_init,
    apply_sync,
    plan_init,
    plan_sync,
)


if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


def _python_project(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "consumer"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n',
        encoding="utf-8",
    )


def test_sync_service_plans_and_applies_without_cli_state(tmp_path: Path) -> None:
    plan = plan_sync(tmp_path, configs=("ruff", "ruff"))

    assert tuple(target.name for target in plan.targets) == ("ruff",)
    result = apply_sync(plan)

    assert result.status == 0
    assert result.count(SyncOutcome.WRITTEN) == 1
    assert (tmp_path / ".ruff-strict.toml").is_file()


def test_sync_service_reports_current_config_as_ok_without_rewriting(tmp_path: Path) -> None:
    plan = plan_sync(tmp_path, configs=("ruff",))
    first = apply_sync(plan)
    before = plan.targets[0].destination.stat().st_mtime_ns

    second = apply_sync(plan, force=True)

    assert first.count(SyncOutcome.WRITTEN) == 1
    assert second.count(SyncOutcome.OK) == 1
    assert second.count(SyncOutcome.WRITTEN) == 0
    assert plan.targets[0].destination.stat().st_mtime_ns == before


def test_sync_service_routes_mobile_configs_to_their_language_roots(tmp_path: Path) -> None:
    swift = tmp_path / "ios"
    kotlin = tmp_path / "android"
    swift.mkdir()
    kotlin.mkdir()

    plan = plan_sync(
        tmp_path,
        configs=("swiftformat", "swiftlint", "ktlint", "detekt", "mobile-security"),
        swift_dest="ios",
        kotlin_dest="android",
    )

    assert {target.name: target.destination.relative_to(tmp_path).as_posix() for target in plan.targets} == {
        "swiftformat": "ios/.swiftformat",
        "swiftlint": "ios/.swiftlint.yml",
        "ktlint": "android/.editorconfig",
        "detekt": "android/config/detekt/detekt.yml",
        "mobile-security": ".mobsf",
        "mobile-mintfile": "Mintfile.mobile.strict",
        "mobile-tool-versions": "mobile-tools.versions.json",
    }


def test_init_service_applies_configs_wiring_and_manifest(tmp_path: Path) -> None:
    _python_project(tmp_path)
    plan = plan_init(tmp_path)

    result = apply_init(plan, install=False)

    assert result.status == 0
    assert (tmp_path / ".ruff-strict.toml").is_file()
    assert (tmp_path / ".pyright-strict.json").is_file()
    assert (tmp_path / ".basedpyright-strict.json").is_file()
    assert (tmp_path / "pyright.strict.json").is_file()
    assert manifest.load(tmp_path) is not None
    assert 'extend = ".ruff-strict.toml"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert (tmp_path / ".github" / "workflows" / "standards.yml").is_file()
    precommit = (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert ("uvx --no-config --isolated --python 3.14 --from sarj-standards-bootstrap code-standards") in precommit
    assert "verbose: true" not in precommit


@pytest.mark.parametrize(
    "configs",
    [("yamllint",), ("zizmor",), ("checkov",), ("zizmor", "checkov")],
    ids=("shared-only", "actions-only", "infrastructure-only", "both-security-tools"),
)
def test_setup_prepares_only_selected_security_tools_and_writes_their_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configs: tuple[str, ...]
) -> None:
    (tmp_path / "main.tf").write_text('resource "terraform_data" "example" {}\n', encoding="utf-8")
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\non: push\njobs: {}\n", encoding="utf-8")
    log = tmp_path / "prepared-tools.txt"
    binaries = tmp_path / "bin"
    binaries.mkdir()
    executable = binaries / "uvx"
    executable.write_text(
        "#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n"
        f"with Path({str(log)!r}).open('a') as output:\n"
        "    output.write(' '.join(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    native_log = tmp_path / "prepared-native-tools.txt"
    mise = binaries / "mise"
    mise.write_text(executable.read_text().replace(str(log), str(native_log)), encoding="utf-8")
    mise.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries), prepend=":")

    plan = plan_init(tmp_path, configs=configs, hook_manager="none")
    result = apply_init(plan)

    assert result.status == 0
    selected = set(configs) & {"zizmor", "checkov"}
    adopted = manifest.load(tmp_path)
    assert adopted is not None
    assert set(adopted.enabled_capabilities) & {"zizmor", "checkov"} == selected
    calls = log.read_text().splitlines() if log.exists() else []
    assert len(calls) == len(selected)
    native_calls = native_log.read_text().splitlines()
    assert len(native_calls) == 2
    assert native_calls[0] == (
        "--no-config --no-env --no-hooks install "
        "aqua:rhysd/actionlint@1.7.12 aqua:koalaman/shellcheck@0.11.0 "
        "aqua:hashicorp/terraform@1.15.8 aqua:terraform-linters/tflint@0.63.1"
    )
    assert "exec aqua:terraform-linters/tflint@0.63.1 -- tflint --config " in native_calls[1]
    assert native_calls[1].endswith(" --init")
    assert not any("zizmor" in call for call in native_calls)
    generated = (tmp_path / ".github/workflows/standards.yml").read_text()
    for tool, target in (("zizmor", "zizmor.yml"), ("checkov", ".checkov.yml")):
        assert (tmp_path / target).is_file() == (tool in selected)
        assert (f"Prepare pinned {tool}" in generated) == (tool in selected)
        assert any(f"{tool}==" in call and "--version" in call for call in calls) == (tool in selected)
    assert all("--offline" not in call for call in calls)


def test_setup_existing_old_bundle_does_not_prepare_unadopted_security_tools(tmp_path: Path) -> None:
    (tmp_path / "main.tf").write_text('resource "terraform_data" "example" {}\n', encoding="utf-8")
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\non: push\njobs: {}\n", encoding="utf-8")
    disabled = [name for name in manifest.ALL_CAPABILITIES if name not in {"yamllint", "zizmor", "checkov"}]
    (tmp_path / manifest.MANIFEST_NAME).write_text(
        f'schema = 4\nbundle = "8.12.1"\n[capabilities]\ndisable = {json.dumps(disabled)}\n[hooks]\nmanager = "none"\n',
        encoding="utf-8",
    )

    plan = plan_init(tmp_path)

    assert plan.scaffold.configs == ("yamllint",)
    assert plan.install_commands == ()
    assert plan.sync is not None
    assert all(target.name not in {"zizmor", "checkov"} for target in plan.sync.targets)


def test_init_service_deletes_the_retired_managed_launcher_idempotently(tmp_path: Path) -> None:
    _python_project(tmp_path)
    retired = tmp_path / launcher.RETIRED_REPOSITORY_LAUNCHER
    retired.parent.mkdir()
    retired.write_text(launcher.retired_repository_script(), encoding="utf-8")

    first = plan_init(tmp_path)

    assert first.scaffold.deletes == [retired]
    assert apply_init(first, install=False).status == 0
    assert not retired.exists()

    second = plan_init(tmp_path)

    assert second.scaffold.deletes == []
    assert apply_init(second, install=False).status == 0
    assert not retired.exists()


def test_init_service_refuses_to_delete_a_custom_retired_launcher(tmp_path: Path) -> None:
    _python_project(tmp_path)
    retired = tmp_path / launcher.RETIRED_REPOSITORY_LAUNCHER
    retired.parent.mkdir()
    retired.write_text(f"{launcher.retired_repository_script()}\n# consumer edit\n", encoding="utf-8")

    plan = plan_init(tmp_path)
    result = apply_init(plan, install=False)

    assert result.status == 2
    assert plan.scaffold.errors == [f"refusing to remove customized retired launcher: {retired}"]
    assert retired.read_text(encoding="utf-8").endswith("# consumer edit\n")


def test_init_service_remains_python_only_after_adoption(tmp_path: Path) -> None:
    _python_project(tmp_path)
    first = plan_init(tmp_path)
    assert apply_init(first, install=False).status == 0

    second = plan_init(tmp_path)

    assert second.scaffold.ecosystems.python
    assert not second.scaffold.ecosystems.typescript
    assert all(command.argv[0] != "npm" for command in second.install_commands)


def test_init_service_rejects_absent_target_created_after_planning(tmp_path: Path) -> None:
    _python_project(tmp_path)
    plan = plan_init(tmp_path)
    target = tmp_path / ".ruff-strict.toml"
    target.write_text("late user file\n", encoding="utf-8")

    result = apply_init(plan, install=False)

    assert result.status == 2
    assert result.error is not None
    assert "stale" in result.error
    assert target.read_text(encoding="utf-8") == "late user file\n"


def test_init_service_rolls_back_every_file_when_install_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _python_project(tmp_path)
    original = (tmp_path / "pyproject.toml").read_bytes()
    retired = tmp_path / launcher.RETIRED_REPOSITORY_LAUNCHER
    retired.parent.mkdir()
    retired_bytes = launcher.retired_repository_script().encode()
    retired.write_bytes(retired_bytes)
    plan = plan_init(tmp_path)

    def fail_install(_commands: Iterable[lifecycle.Command]) -> int:
        return 7

    monkeypatch.setattr(lifecycle, "execute", fail_install)  # sarj-noqa: SARJ445 -- intercepts setup failure dispatch
    result = apply_init(plan)

    assert result.status == 2
    assert result.error == "dependency or hook installer exited with status 7"
    assert result.failure is InitFailure.INSTALL
    assert (tmp_path / "pyproject.toml").read_bytes() == original
    assert not (tmp_path / ".ruff-strict.toml").exists()
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()
    assert retired.read_bytes() == retired_bytes
