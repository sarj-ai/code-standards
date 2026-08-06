"""Install, inspect, verify, and format an adopted repository."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
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
    argv: Sequence[str]
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
    if ecosystems.python_root is not None and _has_legacy_in_project_bundle(ecosystems.python_root):
        commands.append(
            Command(
                "remove legacy in-project standards",
                ("uv", "remove", "--dev", "sarj-lint-configs"),
                ecosystems.python_root,
            )
        )
    if (root / ".git").exists() and hook_manager == "pre-commit":
        hook_argv = ("uvx", "--from", "pre-commit", "pre-commit", "install", "--hook-type", "pre-commit")
        commands.append(Command("pre-commit hooks", hook_argv, root))
    return commands


def _has_legacy_in_project_bundle(python_root: Path) -> bool:
    pyproject = python_root / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(r"(?i)\bsarj[-_]lint[-_]configs\s*(?:\[[^]]+\])?\s*(?:==|>=|<=|~=|!=|>|<|@)", text) is not None


def verification_commands(ecosystems: scaffold.Ecosystems) -> list[Command]:
    commands: list[Command] = []
    if ecosystems.python_root is not None:
        for project in _python_verification_roots(ecosystems.python_root):
            commands.extend(
                (
                    Command("Ruff", (_environment_binary("ruff"), "check", "."), project),
                    Command("BasedPyright", (_environment_binary("basedpyright"),), project),
                )
            )
    if ecosystems.typescript_root is not None:
        commands.append(
            Command("ESLint", packagemanager.exec_argv(ecosystems.client, "eslint", "."), ecosystems.typescript_root)
        )
    return commands


def selected_eslint_commands(root: Path, paths: Iterable[str], *, label: str = "selected") -> list[Command]:
    """Build package-manager-aware ESLint commands for every selected JS/TS project.

    Pre-commit passes paths relative to the repository, while callers may pass
    absolute paths.  ESLint must run from the detected TypeScript project so it
    resolves that project's flat config, TypeScript project, and package tree.
    Deleted files, symlinks, paths outside the repository, and files belonging
    to another project are deliberately omitted.
    """
    repository = root.resolve()
    candidates = _selected_eslint_candidates(repository, paths)
    if not candidates:
        return []
    grouped: dict[Path, set[str]] = {}
    unowned: list[Path] = []
    for candidate in candidates:
        project = _owning_typescript_project(candidate, repository)
        if project is None:
            unowned.append(candidate)
            continue
        grouped.setdefault(project, set()).add(candidate.relative_to(project).as_posix())
    if unowned and label == "analysis":
        msg = f"no TypeScript project accepts {len(unowned)} selected JavaScript/TypeScript path(s)"
        raise ValueError(msg)
    commands: list[Command] = []
    for project, scoped in sorted(grouped.items(), key=lambda item: str(item[0])):
        install_root = packagemanager.workspace_root(project, repository)
        client = packagemanager.detect(install_root)
        commands.append(
            Command(
                f"ESLint ({label}: {project.relative_to(repository).as_posix() or '.'})",
                packagemanager.exec_argv(client, "eslint", "--", *sorted(scoped)),
                project,
            )
        )
    return commands


def _owning_typescript_project(candidate: Path, repository: Path) -> Path | None:
    start = candidate if candidate.is_dir() else candidate.parent
    bounded = (start, *(parent for parent in start.parents if parent == repository or repository in parent.parents))
    config_names = ("eslint.config.js", "eslint.config.cjs", "eslint.config.mjs", "eslint.config.ts")
    configured = next((path for path in bounded if any((path / name).is_file() for name in config_names)), None)
    if configured is not None:
        return configured
    lock_names = tuple(name for name, _client in packagemanager.LOCKFILES)
    locked = next((path for path in bounded if any((path / name).is_file() for name in lock_names)), None)
    if locked is not None:
        return locked
    return next((path for path in bounded if (path / "package.json").is_file()), None)


def staged_eslint_commands(root: Path, paths: Iterable[str]) -> list[Command]:
    """Compatibility wrapper for hook callers."""
    return selected_eslint_commands(root, paths, label="staged")


def _selected_eslint_candidates(root: Path, paths: Iterable[str]) -> set[Path]:
    candidates: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        unresolved = path if path.is_absolute() else root / path
        if is_link_like(unresolved):
            continue
        candidate = unresolved.resolve()
        if not candidate.is_relative_to(root):
            continue
        if candidate.is_dir() and candidate.name not in _PROJECT_SKIP_DIRS:
            sources = _eslint_sources(candidate)
            owners = {_owning_typescript_project(source, root) for source in sources}
            candidate_owner = _owning_typescript_project(candidate, root)
            if sources and owners == {candidate_owner} and candidate_owner is not None:
                candidates.add(candidate)
            else:
                candidates.update(sources)
        elif candidate.suffix.lower() in _ESLINT_SUFFIXES and candidate.is_file():
            candidates.add(candidate)
    return candidates


def _contains_eslint_source(directory: Path) -> bool:
    return next(iter(_eslint_sources(directory)), None) is not None


def _eslint_sources(directory: Path) -> set[Path]:
    sources: set[Path] = set()
    for parent, directories, names in os.walk(directory):
        base = Path(parent)
        directories[:] = [
            name for name in directories if name not in _PROJECT_SKIP_DIRS and not is_link_like(base / name)
        ]
        sources.update(
            base / name
            for name in names
            if Path(name).suffix.lower() in _ESLINT_SUFFIXES and not is_link_like(base / name)
        )
    return sources


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
    _ = command
    environment = os.environ.copy()  # ruff: ignore[banned-api] -- tools must not mistake the isolated runner for the consumer environment.
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
