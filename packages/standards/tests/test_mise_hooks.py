from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.cli.main import main
from sarj_standards.libs.adoption import hooks, launcher, scaffold


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("manager", ["pre-commit", "lefthook"])
def test_setup_and_doctor_repair_ignore_mise_and_are_idempotent(tmp_path: Path, manager: str) -> None:
    mise = tmp_path / "mise.toml"
    mise.write_text("[tools\n", encoding="utf-8")
    if manager == "lefthook":
        (tmp_path / "lefthook.yml").write_text("pre-commit:\n  commands: {}\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "setup", "--hooks", manager, "--config", "taplo", "--no-install"]) == 0
    assert main(["--root", str(tmp_path), "doctor", "--repair", "--no-install"]) == 0
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert main(["--root", str(tmp_path), "doctor", "--repair", "--no-install"]) == 0
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before
    hook_path = tmp_path / ("lefthook.yml" if manager == "lefthook" else ".pre-commit-config.yaml")
    assert hook_path.read_text(encoding="utf-8").count(launcher.repository_command()) == 2
    assert "==" not in hook_path.read_text(encoding="utf-8")
    assert mise.read_text(encoding="utf-8") == "[tools\n"
    assert scaffold.standards_check_workflows(tmp_path) == (tmp_path / ".github" / "workflows" / "standards.yml",)


def test_precommit_generation_uses_same_bootstrap_for_both_stages(tmp_path: Path) -> None:
    text = "repos:\n" + scaffold.precommit_block()
    (tmp_path / ".pre-commit-config.yaml").write_text(text, encoding="utf-8")
    assert hooks.precommit_runs_staged_check(tmp_path)
    assert hooks.precommit_runs_commit_message_check(tmp_path)
    assert text.count(launcher.repository_command()) == 2
    assert "==" not in text
    assert "mise exec" not in text


@pytest.mark.parametrize(
    "prefix",
    [
        "mise exec pipx:sarj-standards-bootstrap -- code-standards",
        "uvx --no-config --isolated --python 3.14 --from sarj-standards-bootstrap==2.0.3 code-standards",
    ],
)
def test_doctor_migrates_repository_and_hook_commands_together(tmp_path: Path, prefix: str) -> None:
    assert main(["--root", str(tmp_path), "setup", "--hooks", "pre-commit", "--config", "taplo", "--no-install"]) == 0
    hook_path = tmp_path / ".pre-commit-config.yaml"
    hook_path.write_text(
        hook_path.read_text(encoding="utf-8").replace(launcher.repository_command(), prefix), encoding="utf-8"
    )
    makefile = tmp_path / "Makefile"
    makefile.write_text(f"check:\n\t{prefix} check\n\techo unrelated\n", encoding="utf-8")

    assert main(["--root", str(tmp_path), "doctor", "--repair", "--no-install"]) == 0
    assert hook_path.read_text(encoding="utf-8").count(launcher.repository_command()) == 2
    assert (
        makefile.read_text(encoding="utf-8") == f"check:\n\t{launcher.repository_command()} check\n\techo unrelated\n"
    )
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert main(["--root", str(tmp_path), "doctor", "--repair", "--no-install"]) == 0
    assert {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("layout", ["commands", "jobs"])
@pytest.mark.parametrize(
    "prefix",
    [
        "mise exec pipx:sarj-standards-bootstrap -- code-standards",
        "uvx --no-config --isolated --python 3.14 --from sarj-standards-bootstrap==2.0.3 code-standards",
        "uvx --no-config --isolated --python 3.14 --from code-standards==7.11.0 code-standards",
    ],
)
def test_lefthook_migration_preserves_other_commands_and_is_idempotent(
    tmp_path: Path, layout: str, prefix: str
) -> None:
    marker = "    standards:" if layout == "commands" else "    - name: standards"
    unrelated = "    unrelated:" if layout == "commands" else "    - name: unrelated"
    original = (
        f"# preserve me\npre-commit:\n  {layout}:\n{marker}\n"
        f"      run: {prefix} check --staged --trust-repository-code -- {{staged_files}}\n"
        f"{unrelated}\n      run: echo unrelated\n"
        f"commit-msg:\n  {layout}:\n{marker}\n      run: {prefix} commit-message {{1}}\n"
    )
    config = tmp_path / "lefthook.yml"
    config.write_text(original, encoding="utf-8")
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
    assert migrated.count('commit-message "{1}"') == 1
    assert migrated.count(launcher.repository_command()) == 2
    assert "==" not in migrated
    assert "mise exec" not in migrated
    assert hooks.wire_lefthook_staged_check(tmp_path).contents == migrated
    assert hooks.wire_lefthook_commit_message_check(tmp_path).contents == migrated
