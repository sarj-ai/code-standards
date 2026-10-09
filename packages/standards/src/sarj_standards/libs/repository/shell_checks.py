from __future__ import annotations

from pathlib import Path
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- catches bounded native analysis failures.
from typing import Annotated, Literal

import typer

from sarj_standards.libs.linting.devops_tools import NativeToolError, checked_tool
from sarj_standards.libs.linting.external import run_process


app = typer.Typer(help="Run the repository's pinned native shell checks")


@app.command()
def main(
    root: Annotated[Path, typer.Option("--root")],
    tool: Annotated[Literal["shellcheck", "shfmt"], typer.Option("--tool")],
) -> None:
    raise typer.Exit(check(root.resolve(), tool=tool))


def check(root: Path, *, tool: Literal["shellcheck", "shfmt"]) -> int:
    files = tuple(str(path) for path in sorted((root / ".github/scripts").glob("*.sh")))
    if not files:
        return 0
    arguments = (
        (
            "--norc",
            "--extended-analysis=true",
            "--enable=check-extra-masked-returns",
            "--severity=info",
            "--source-path=SCRIPTDIR",
            "--",
        )
        if tool == "shellcheck"
        else ("-d", "-i", "2")
    )
    try:
        result = run_process((str(_executable(tool, root)), *arguments, *files), cwd=root)
    except (OSError, subprocess.SubprocessError, NativeToolError) as error:
        typer.echo(f"{tool}: {error}", err=True)
        return 2
    else:
        typer.echo(result.stdout, nl=False)
        typer.echo(result.stderr, nl=False, err=True)
        return result.returncode


def _executable(name: str, root: Path) -> Path:
    native = checked_tool(name, root=root)
    if native.executable is None:
        message = f"{name} did not resolve an attested executable"
        raise NativeToolError(message)
    return native.executable


if __name__ == "__main__":
    app()
