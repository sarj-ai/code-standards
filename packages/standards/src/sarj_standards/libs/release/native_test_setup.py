from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from sarj_standards.libs.adoption import devops, lifecycle
from sarj_standards.libs.linting.devops_tools import checked_tool


app = typer.Typer(help="Provision pinned native tools for the package's integration tests")


@app.command()
def main(root: Annotated[Path, typer.Option("--root")]) -> None:
    raise typer.Exit(setup(root.resolve()))


def setup(root: Path) -> int:
    # This suite exercises native workflow/shell parsing and prepared Helm/Kubernetes
    # artifacts regardless of the repository's consumer capability opt-outs.
    files = (root / ".github/workflows/ci.yml",)
    commands = devops.install_commands(root, files, prepared=True)
    status = lifecycle.execute(commands)
    if status:
        return status
    directories: set[Path] = set()
    for name in devops.required_tools(root, files, prepared=True):
        tool = checked_tool(name, root=root)
        if tool.executable is None:
            message = f"installed {name} has no attested executable"
            raise ValueError(message)
        directories.add(tool.executable.parent)
    with Path(os.environ["GITHUB_PATH"]).open("a", encoding="utf-8") as stream:  # ruff: ignore[banned-api] -- GitHub's runner-owned native executable handoff.
        stream.writelines(f"{directory}\n" for directory in sorted(directories))
    return 0


if __name__ == "__main__":
    app()
