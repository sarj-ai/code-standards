from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

import pytest

from sarj_standards.cli.main import main
from sarj_standards.libs.adoption import hooks, launcher, manifest, scaffold


if TYPE_CHECKING:
    from pathlib import Path


def _opt_in(root: Path) -> None:
    (root / "mise.toml").write_text(
        "[tools]\n"
        f'"{launcher.MISE_BOOTSTRAP_TOOL}" = '
        f'{{ version = "{launcher.BOOTSTRAP_VERSION}", uvx_args = "{launcher.MISE_UVX_ARGS}" }}\n',
        encoding="utf-8",
    )


@pytest.mark.parametrize("manager", ["pre-commit", "lefthook"])
def test_mise_setup_and_doctor_repair_keep_single_pin_and_are_idempotent(tmp_path: Path, manager: str) -> None:
    _opt_in(tmp_path)
    if manager == "lefthook":
        (tmp_path / "lefthook.yml").write_text("pre-commit:\n  commands: {}\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "setup", "--hooks", manager, "--config", "taplo", "--no-install"]) == 0
    assert main(["--root", str(tmp_path), "doctor", "--repair", "--no-install"]) == 0
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert main(["--root", str(tmp_path), "doctor", "--repair", "--no-install"]) == 0
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before
    hook_path = tmp_path / ("lefthook.yml" if manager == "lefthook" else ".pre-commit-config.yaml")
    assert launcher.BOOTSTRAP_SPEC not in hook_path.read_text(encoding="utf-8")
    assert scaffold.standards_check_workflows(tmp_path) == (tmp_path / ".github" / "workflows" / "standards.yml",)


@pytest.mark.parametrize("mise", [False, True])
def test_precommit_generation_uses_repository_launcher_only_when_opted_in(tmp_path: Path, mise: bool) -> None:
    if mise:
        _opt_in(tmp_path)
    text = "repos:\n" + scaffold.precommit_block(root=tmp_path)
    (tmp_path / ".pre-commit-config.yaml").write_text(text, encoding="utf-8")
    assert hooks.precommit_runs_staged_check(tmp_path)
    assert hooks.precommit_runs_commit_message_check(tmp_path)
    assert text == "repos:\n" + scaffold.precommit_block(root=tmp_path)
    if mise:
        assert text.count(f"mise exec {launcher.MISE_BOOTSTRAP_TOOL} -- code-standards") == 2
        assert "==" not in text
    else:
        assert launcher.BOOTSTRAP_SPEC in text
        assert f"code-standards=={manifest.adopted_version()}" in text
        assert "mise exec" not in text


@pytest.mark.parametrize("layout", ["commands", "jobs"])
@pytest.mark.parametrize("mise", [False, True])
def test_lefthook_migration_preserves_other_commands_and_is_idempotent(tmp_path: Path, layout: str, mise: bool) -> None:
    staged = launcher.repository_command("check", "--staged", "--trust-repository-code", "--") + " {staged_files}"
    message = shlex.join(launcher.argv(version=manifest.adopted_version())) + " commit-message {1}"
    marker = "    standards:" if layout == "commands" else "    - name: standards"
    unrelated = "    unrelated:" if layout == "commands" else "    - name: unrelated"
    original = (
        f"# preserve me\npre-commit:\n  {layout}:\n{marker}\n      run: {staged}\n"
        f"{unrelated}\n      run: echo unrelated\n"
        f"commit-msg:\n  {layout}:\n{marker}\n      run: {message}\n"
    )
    config = tmp_path / "lefthook.yml"
    config.write_text(original, encoding="utf-8")
    if mise:
        _opt_in(tmp_path)
        assert not hooks.lefthook_runs_staged_check(tmp_path)
        assert not hooks.lefthook_runs_commit_message_check(tmp_path)
    staged_write = hooks.wire_lefthook_staged_check(tmp_path)
    migrated = hooks.wire_lefthook_commit_message_check(tmp_path, contents=staged_write.contents).contents
    config.write_text(migrated, encoding="utf-8")
    assert hooks.lefthook_runs_staged_check(tmp_path)
    assert hooks.lefthook_runs_commit_message_check(tmp_path)
    assert "# preserve me" in migrated
    assert "run: echo unrelated" in migrated
    assert migrated.count("check --staged") == 1
    expected_argument = '"{1}"' if mise else "{1}"
    assert migrated.count(f"commit-message {expected_argument}") == 1
    assert hooks.wire_lefthook_staged_check(tmp_path).contents == migrated
    assert hooks.wire_lefthook_commit_message_check(tmp_path).contents == migrated
    if mise:
        assert "==" not in migrated
    else:
        assert migrated == original
