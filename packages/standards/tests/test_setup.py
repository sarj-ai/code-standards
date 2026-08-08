"""Repository setup is planned by the package rather than by shell recipes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sarj_standards.cli.main as cli
from sarj_standards.libs.setup import plan_setup


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_setup_plan_owns_every_development_environment(tmp_path: Path) -> None:
    plan = plan_setup(tmp_path)
    commands = plan.commands

    assert plan.install_hooks
    assert [command.argv[:2] for command in commands] == [
        ("uv", "sync"),
        ("uv", "sync"),
        ("uv", "sync"),
        ("uv", "sync"),
        ("npm", "ci"),
        ("npm", "ci"),
    ]
    assert commands[-2].argv == ("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund")
    assert commands[-1].argv == ("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund")
    assert commands[-2].cwd == tmp_path / "packages" / "typescript"
    assert commands[-1].cwd == tmp_path / "apps" / "docs"


def test_setup_check_reports_hooks_and_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--root", str(tmp_path), "maintain", "setup", "--check"]) == 0

    output = capsys.readouterr().out
    assert "would install: Lefthook repository hooks" in output
    assert output.count("would run:") == 6
