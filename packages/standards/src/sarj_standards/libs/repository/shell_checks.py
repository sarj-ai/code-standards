from __future__ import annotations

from pathlib import Path
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- catches bounded native analysis failures.
from typing import Annotated, Literal

import typer

from sarj_standards.libs.linting.devops_tools import NativeToolError, checked_tool
from sarj_standards.libs.linting.external import ProcessOutput, parse_shellcheck, run_process
from sarj_standards.libs.linting.shell_policy import SHELLCHECK_ARGS, WARNING_RULES


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
    arguments = (*SHELLCHECK_ARGS, "--") if tool == "shellcheck" else ("-d", "-i", "2", "-ci")
    try:
        result = run_process((str(_executable(tool, root)), *arguments, *files), cwd=root)
        if tool == "shellcheck":
            return _shellcheck_status(result, root)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        typer.echo(f"{tool}: {error}", err=True)
        return 2
    else:
        typer.echo(result.stdout, nl=False)
        typer.echo(result.stderr, nl=False, err=True)
        return result.returncode


def _shellcheck_status(result: ProcessOutput, root: Path) -> int:
    findings = parse_shellcheck(result.stdout, root=root)
    if result.returncode not in {0, 1} or result.stderr.strip() or (result.returncode == 1 and not findings):
        message = result.stderr.strip() or "incomplete ShellCheck protocol"
        raise NativeToolError(message)
    for finding in findings:
        point = finding.location.region.start if finding.location.region is not None else finding.location.position
        location = finding.location.path
        if point is not None:
            location += f":{point.line + 1}:{point.character + 1}"
        typer.echo(f"{location}: {finding.severity.value} {finding.code} {finding.message}")
    return int(any(finding.rule_id not in WARNING_RULES for finding in findings))


def _executable(name: str, root: Path) -> Path:
    native = checked_tool(name, root=root)
    if native.executable is None:
        message = f"{name} did not resolve an attested executable"
        raise NativeToolError(message)
    return native.executable


if __name__ == "__main__":
    app()
