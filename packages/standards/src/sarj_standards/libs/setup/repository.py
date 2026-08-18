from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sarj_standards.libs.adoption.lifecycle import Command, execute
from sarj_standards.libs.repository import hooks


@dataclass(frozen=True, slots=True)
class SetupPlan:
    root: Path
    commands: tuple[Command, ...]
    install_hooks: bool = True


def plan_setup(root: Path) -> SetupPlan:
    resolved = root.resolve()
    commands = (
        *(
            Command("Python package", ("uv", "sync", "--frozen"), resolved / "packages" / name)
            for name in ("python", "sql", "iac", "standards")
        ),
        Command(
            "TypeScript package",
            ("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"),
            resolved / "packages" / "typescript",
        ),
        Command(
            "Documentation site",
            ("npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"),
            resolved / "apps" / "docs",
        ),
    )
    return SetupPlan(resolved, install_hooks=True, commands=commands)


def apply_setup(plan: SetupPlan) -> int:
    hook_status = hooks.install(plan.root) if plan.install_hooks else 0
    return hook_status or execute(plan.commands)
