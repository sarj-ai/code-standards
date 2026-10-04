from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
from typing import Annotated

from pathspec import PathSpec
import typer

from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.diagnostics import Completion, Severity, TrustMode, to_text

from .analysis import report_from_tools
from .external import analyze_oxlint_project
from .formatting import analyze_formatting
from .policy import Policy
from .runner import group_paths


_APP = typer.Typer(add_completion=False)


def _selection_policy(cwd: Path, exclusions: list[str]) -> Policy:
    root = next((parent for parent in (cwd, *cwd.parents) if (parent / manifest.MANIFEST_NAME).is_file()), cwd)
    policy = Policy.from_manifest(root, manifest.load(root))
    prefix = cwd.relative_to(root).as_posix()
    patterns = [name if prefix == "." else f"{prefix}/{name}" for name in exclusions]
    return replace(policy, excluded_paths=policy.excluded_paths + PathSpec.from_lines("gitignore", patterns))


@_APP.command()
def check(
    config: Annotated[Path, typer.Option("--config")],
    paths: Annotated[list[str], typer.Argument()],
    *,
    deny_warnings: Annotated[bool, typer.Option("--deny-warnings")] = False,
    format_files: Annotated[bool, typer.Option("--format")] = False,
    exclude: Annotated[list[str] | None, typer.Option("--exclude")] = None,
) -> None:
    cwd = Path.cwd().resolve()
    policy = _selection_policy(cwd, exclude or [])
    inputs = [str(cwd / name) for name in paths]
    selected = group_paths(inputs, policy=policy).typescript
    tools = [analyze_oxlint_project(selected, root=policy.root, config=config.resolve())]
    if format_files:
        tools.append(analyze_formatting(inputs, root=policy.root, trust=TrustMode.TRUSTED, policy=policy))
    report = report_from_tools(policy.root, tools)
    sys.stdout.write(to_text(report))
    if any(tool.completion is not Completion.COMPLETE for tool in tools):
        raise typer.Exit(2)
    if deny_warnings and any(item.severity is Severity.WARNING for item in report.diagnostics):
        raise typer.Exit(1)
    raise typer.Exit(report.exit_code)


def main(argv: list[str] | None = None) -> None:
    _APP(args=argv)


if __name__ == "__main__":
    main()
