"""Repository setup is planned by the package rather than by shell recipes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_lint_configs.libs.setup import plan_setup


if TYPE_CHECKING:
    from pathlib import Path


def test_setup_plan_owns_every_development_environment(tmp_path: Path) -> None:
    commands = plan_setup(tmp_path).commands

    assert [command.argv[:2] for command in commands] == [
        ("uv", "sync"),
        ("uv", "sync"),
        ("uv", "sync"),
        ("uv", "sync"),
        ("npm", "ci"),
    ]
    assert commands[-1].cwd == tmp_path / "packages" / "typescript"
