from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

import pytest

from sarj_standards.cli.main import main
from sarj_standards.libs.adoption import doctor, hooks, launcher, manifest, scaffold


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("manager", ["pre-commit", "lefthook"])
def test_manifestless_commit_policy_uses_direct_release_and_repairs_idempotently(
    tmp_path: Path, manager: manifest.HookManager
) -> None:
    if manager == "lefthook":
        (tmp_path / "lefthook.yml").write_text("pre-commit:\n  commands: {}\n", encoding="utf-8")
    plan = scaffold.build_commit_policy_plan(tmp_path, force=False, hook_manager=manager)
    assert not plan.errors
    scaffold.apply(plan)
    assert not manifest.manifest_path(tmp_path).exists()
    path = tmp_path / ("lefthook.yml" if manager == "lefthook" else ".pre-commit-config.yaml")
    contents = path.read_text(encoding="utf-8")
    assert shlex.join(launcher.argv(version=manifest.adopted_version())) in contents
    assert "sarj-standards-bootstrap" not in contents
    assert contents.count(" commit-message") == 1
    assert doctor.is_commit_policy_only(tmp_path)
    assert (
        hooks.lefthook_runs_commit_message_check(tmp_path)
        if manager == "lefthook"
        else hooks.precommit_runs_commit_message_check(tmp_path)
    )
    assert main(["--root", str(tmp_path), "doctor", "--repair", "--no-install"]) == 0
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert main(["--root", str(tmp_path), "doctor", "--repair", "--no-install"]) == 0
    assert {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("manager", ["pre-commit", "lefthook"])
def test_full_adoption_after_commit_only_migrates_to_bootstrap(tmp_path: Path, manager: manifest.HookManager) -> None:
    if manager == "lefthook":
        (tmp_path / "lefthook.yml").write_text("pre-commit:\n  commands: {}\n", encoding="utf-8")
    scaffold.apply(scaffold.build_commit_policy_plan(tmp_path, force=False, hook_manager=manager))
    assert main(["--root", str(tmp_path), "setup", "--hooks", manager, "--config", "taplo", "--no-install"]) == 0
    assert manifest.manifest_path(tmp_path).is_file()
    path = tmp_path / ("lefthook.yml" if manager == "lefthook" else ".pre-commit-config.yaml")
    contents = path.read_text(encoding="utf-8")
    assert contents.count(launcher.repository_command()) == 2
    assert contents.count(" commit-message") == 1
    assert "==" not in contents
    assert main(["--root", str(tmp_path), "doctor", "--repair", "--no-install"]) == 0
    assert path.read_text(encoding="utf-8") == contents
