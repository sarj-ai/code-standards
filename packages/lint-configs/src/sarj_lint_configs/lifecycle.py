"""Install, inspect, verify, and format an adopted repository."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- commands are fixed argv assembled from detected ecosystems.
import sys
from typing import TYPE_CHECKING

from . import manifest, packagemanager, runner, scaffold


if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True, slots=True)
class Command:
    label: str
    argv: tuple[str, ...]
    cwd: Path


@dataclass(frozen=True, slots=True)
class Inspection:
    adopted_version: str | None
    installed_version: str
    configs: tuple[str, ...]
    python_root: str | None
    typescript_root: str | None
    package_manager: str | None


def install_commands(root: Path, ecosystems: scaffold.Ecosystems) -> list[Command]:
    commands: list[Command] = []
    if ecosystems.python_root is not None:
        commands.append(
            Command(
                "Python standards",
                ("uv", "add", "--dev", f"sarj-lint-configs=={manifest.adopted_version()}"),
                ecosystems.python_root,
            )
        )
    if ecosystems.typescript_root is not None:
        commands.append(
            Command(
                "ESLint peers",
                packagemanager.install_argv(ecosystems.client),
                ecosystems.typescript_root,
            )
        )
    if (root / ".git").exists():
        hook_argv = (
            (
                "uv",
                "run",
                "--project",
                str(ecosystems.python_root),
                "pre-commit",
                "install",
            )
            if ecosystems.python_root is not None
            else ("uvx", "--from", "pre-commit", "pre-commit", "install")
        )
        commands.append(Command("pre-commit hooks", hook_argv, root))
    return commands


def verification_commands(ecosystems: scaffold.Ecosystems) -> list[Command]:
    commands: list[Command] = []
    if ecosystems.python_root is not None:
        commands.extend(
            (
                Command("Ruff", (_environment_binary("ruff"), "check", "."), ecosystems.python_root),
                Command("BasedPyright", (_environment_binary("basedpyright"),), ecosystems.python_root),
            )
        )
    if ecosystems.typescript_root is not None:
        commands.append(
            Command("ESLint", packagemanager.exec_argv(ecosystems.client, "eslint", "."), ecosystems.typescript_root)
        )
    return commands


def format_commands(ecosystems: scaffold.Ecosystems) -> list[Command]:
    commands: list[Command] = []
    if ecosystems.python_root is not None:
        commands.extend(
            (
                Command("Ruff format", (_environment_binary("ruff"), "format", "."), ecosystems.python_root),
                Command("Ruff fixes", (_environment_binary("ruff"), "check", "--fix", "."), ecosystems.python_root),
            )
        )
    if ecosystems.typescript_root is not None:
        commands.append(
            Command(
                "ESLint fixes",
                packagemanager.exec_argv(ecosystems.client, "eslint", "--fix", "."),
                ecosystems.typescript_root,
            )
        )
    return commands


def execute(commands: Iterable[Command]) -> int:
    for command in commands:
        executable = shutil.which(command.argv[0])
        if executable is None:
            sys.stderr.write(f"error: {command.argv[0]} is required for {command.label}\n")
            return 2
        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
            [executable, *command.argv[1:]], cwd=command.cwd, check=False
        )
        if completed.returncode:
            return completed.returncode
    return 0


def verify_custom_rules(root: Path) -> int:
    return runner.run([str(root)])


def inspect(root: Path) -> Inspection:
    adopted = manifest.load(root)
    ecosystems = scaffold.detect(root)
    return Inspection(
        adopted_version=adopted.version if adopted else None,
        installed_version=manifest.adopted_version(),
        configs=adopted.configs if adopted else (),
        python_root=_relative(root, ecosystems.python_root),
        typescript_root=_relative(root, ecosystems.typescript_root),
        package_manager=str(ecosystems.client) if ecosystems.typescript else None,
    )


def inspection_json(root: Path) -> str:
    return json.dumps(asdict(inspect(root)), indent=2) + "\n"


def _environment_binary(name: str) -> str:
    found = shutil.which(name, path=str(Path(sys.executable).parent))
    if found is None:
        msg = f"{name} is missing from the sarj-lint-configs environment"
        raise OSError(msg)
    return found


def _relative(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    return path.relative_to(root).as_posix() or "."
