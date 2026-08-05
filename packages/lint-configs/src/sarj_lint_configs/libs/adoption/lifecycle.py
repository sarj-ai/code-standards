"""Install, inspect, verify, and format an adopted repository."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- commands are fixed argv assembled from detected ecosystems.
import sys
from typing import (
    TYPE_CHECKING,
    cast,  # ruff: ignore[banned-api] -- json.loads is typed Any; establish an object boundary before narrowing.
)

from sarj_lint_configs.libs.filesystem import is_link_like
from sarj_lint_configs.libs.linting import runner

from . import manifest, packagemanager, scaffold


if TYPE_CHECKING:
    from collections.abc import Iterable


_PROJECT_SKIP_DIRS = frozenset({".git", ".venv", "build", "dist", "node_modules", "target", "vendor"})
_ESLINT_SUFFIXES = frozenset({".cjs", ".cts", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx"})


@dataclass(frozen=True, slots=True)
class Command:
    label: str
    argv: tuple[str, ...]
    cwd: Path


@dataclass(frozen=True, slots=True)
class Inspection:
    adopted_version: str | None
    profile: manifest.Profile | None
    installed_version: str
    configs: tuple[str, ...]
    python_root: str | None
    typescript_root: str | None
    package_manager: str | None


def install_commands(
    root: Path,
    ecosystems: scaffold.Ecosystems,
    *,
    hook_manager: manifest.HookManager = "pre-commit",
) -> list[Command]:
    commands: list[Command] = []
    if ecosystems.python_root is not None:
        versions = manifest.installed_versions()
        bundle = tuple(f"{name}=={version}" for name, version in versions.items())
        release_age_exemptions = tuple(
            argument for name in versions for argument in ("--exclude-newer-package", f"{name}=2099-12-31")
        )
        commands.append(
            Command(
                "Python standards",
                ("uv", "add", "--dev", *release_age_exemptions, *bundle),
                ecosystems.python_root,
            )
        )
    if ecosystems.typescript_root is not None:
        install_root = ecosystems.typescript_install_root or ecosystems.typescript_root
        is_workspace = install_root != ecosystems.typescript_root or (install_root / "pnpm-workspace.yaml").is_file()
        commands.append(
            Command(
                "ESLint peers",
                packagemanager.install_argv(ecosystems.client, workspace=is_workspace),
                install_root,
            )
        )
    if (root / ".git").exists() and hook_manager == "pre-commit":
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
        for project in _python_verification_roots(ecosystems.python_root):
            commands.extend(
                (
                    Command(
                        "Ruff", ("uv", "run", "--project", str(project), "--frozen", "ruff", "check", "."), project
                    ),
                    Command(
                        "BasedPyright",
                        ("uv", "run", "--project", str(project), "--frozen", "basedpyright"),
                        project,
                    ),
                )
            )
    if ecosystems.typescript_root is not None:
        commands.append(
            Command("ESLint", packagemanager.exec_argv(ecosystems.client, "eslint", "."), ecosystems.typescript_root)
        )
    return commands


def staged_eslint_commands(root: Path, paths: Iterable[str]) -> list[Command]:
    """Build one package-manager-aware ESLint command for staged JS/TS files.

    Pre-commit passes paths relative to the repository, while callers may pass
    absolute paths.  ESLint must run from the detected TypeScript project so it
    resolves that project's flat config, TypeScript project, and package tree.
    Deleted files, symlinks, paths outside the repository, and files belonging
    to another project are deliberately omitted.
    """
    repository = root.resolve()
    candidates = _staged_eslint_candidates(repository, paths)
    if not candidates:
        return []
    ecosystems = scaffold.detect(repository)
    project = ecosystems.typescript_root
    if project is None:
        return []
    project = project.resolve()
    scoped = sorted(
        {
            candidate.relative_to(project).as_posix()
            for candidate in candidates
            if candidate == project or candidate.is_relative_to(project)
        }
    )
    if not scoped:
        return []
    return [
        Command(
            "ESLint (staged)",
            packagemanager.exec_argv(ecosystems.client, "eslint", "--", *scoped),
            project,
        )
    ]


def _staged_eslint_candidates(root: Path, paths: Iterable[str]) -> set[Path]:
    candidates: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        unresolved = path if path.is_absolute() else root / path
        if is_link_like(unresolved):
            continue
        candidate = unresolved.resolve()
        if candidate.suffix.lower() in _ESLINT_SUFFIXES and candidate.is_relative_to(root) and candidate.is_file():
            candidates.add(candidate)
    return candidates


def format_commands(ecosystems: scaffold.Ecosystems) -> list[Command]:
    commands: list[Command] = []
    if ecosystems.python_root is not None:
        for project in _python_verification_roots(ecosystems.python_root):
            commands.extend(
                (
                    Command(
                        "Ruff format",
                        ("uv", "run", "--project", str(project), "--frozen", "ruff", "format", "."),
                        project,
                    ),
                    Command(
                        "Ruff fixes",
                        ("uv", "run", "--project", str(project), "--frozen", "ruff", "check", "--fix", "."),
                        project,
                    ),
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
            [executable, *command.argv[1:]],
            cwd=command.cwd,
            check=False,
            env=_command_environment(command),
        )
        if completed.returncode:
            return completed.returncode
    return 0


def _command_environment(command: Command) -> dict[str, str] | None:
    if command.argv[0] not in {"uv", "uvx"}:
        return None
    environment = os.environ.copy()  # ruff: ignore[banned-api] -- nested uv must not inherit the package runner's venv.
    environment.pop("VIRTUAL_ENV", None)
    return environment


def verify_custom_rules(root: Path, *, paths: Iterable[str] = (".",)) -> int:
    adopted = manifest.load(root)
    baseline = None if adopted is None or adopted.python_baseline is None else str(root / adopted.python_baseline)
    return runner.run([str(root / path) for path in paths], python_baseline=baseline)


def inspect(root: Path) -> Inspection:
    adopted = manifest.load(root)
    ecosystems = scaffold.detect(root)
    return Inspection(
        adopted_version=adopted.version if adopted else None,
        profile=adopted.profile if adopted else None,
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


def _python_verification_roots(root: Path) -> tuple[Path, ...]:
    """Return independently configured Python projects without double-checking an umbrella root."""
    nested = sorted(
        {
            path.parent
            for path in root.glob("**/pyrightconfig.json")
            if not any(part in _PROJECT_SKIP_DIRS for part in path.relative_to(root).parts)
            and (path.parent / "pyproject.toml").is_file()
        },
        key=lambda path: path.as_posix(),
    )
    if not nested:
        return (root,)
    root_config = root / "pyrightconfig.json"
    if root in nested and len(nested) > 1 and not _pyright_has_explicit_scope(root_config):
        nested.remove(root)
    return tuple(nested)


def _pyright_has_explicit_scope(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        parsed = cast("object", json.loads(path.read_text(encoding="utf-8")))
    except OSError, json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and any(key in parsed for key in ("include", "files"))


def _relative(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    return path.relative_to(root).as_posix() or "."
