from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import timedelta
from importlib.metadata import version as distribution_version
from itertools import pairwise
import json
import os
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- commands are fixed argv assembled from detected ecosystems.
import sys
from typing import TYPE_CHECKING, NamedTuple

from sarj_standards.libs.filesystem import is_link_like
from sarj_standards.libs.linting import runner

from . import manifest, packagemanager, scaffold, transaction


if TYPE_CHECKING:
    from collections.abc import Iterable


_PROJECT_SKIP_DIRS = frozenset({".git", ".venv", "build", "dist", "node_modules", "target", "vendor"})
_SKILL_ARTIFACT_ROOTS = frozenset({".agents", ".claude"})
_ESLINT_SUFFIXES = frozenset({".cjs", ".cts", ".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx"})
_COMMAND_TIMEOUT = timedelta(minutes=10)
_GIT_DISCOVERY_TIMEOUT = timedelta(seconds=5)
_GIT_SAFE_ENV = frozenset(
    {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TMPDIR", "XDG_CONFIG_HOME"}
)
_PRECOMMIT_HOOK_LABEL = "pre-commit hooks"
_PRECOMMIT_UVX_MARKER = "# sarj-standards: cache-independent pinned pre-commit fallback"


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


class EslintSelection(NamedTuple):
    commands: tuple[Command, ...]
    unowned_count: int


def install_commands(
    root: Path,
    ecosystems: scaffold.Ecosystems,
    *,
    hook_manager: manifest.HookManager = "pre-commit",
) -> list[Command]:
    commands: list[Command] = []
    if ecosystems.typescript_root is not None:
        install_root = ecosystems.typescript_install_root or ecosystems.typescript_root
        # Setup writes pnpm-workspace.yaml before this command executes because
        # pnpm 11 requires overrides there even for a standalone package.
        is_workspace = (
            ecosystems.client is packagemanager.PackageManager.PNPM
            or install_root != ecosystems.typescript_root
            or (install_root / "pnpm-workspace.yaml").is_file()
        )
        commands.append(
            Command(
                "ESLint peers",
                packagemanager.install_argv(ecosystems.client, workspace=is_workspace, yarn=ecosystems.yarn),
                install_root,
            )
        )
    if ecosystems.python_root is not None and _has_legacy_in_project_bundle(ecosystems.python_root):
        commands.append(
            Command(
                "remove legacy in-project standards",
                ("uv", "remove", "--dev", "sarj-standards"),
                ecosystems.python_root,
            )
        )
    git_metadata = root / ".git"
    if (git_metadata.is_dir() or git_metadata.is_file()) and hook_manager == "pre-commit":
        hook_argv = (
            "uvx",
            "--from",
            f"pre-commit=={distribution_version('pre-commit')}",
            "pre-commit",
            "install",
            "--hook-type",
            "pre-commit",
            "--hook-type",
            "commit-msg",
            "--install-hooks",
        )
        commands.append(Command(_PRECOMMIT_HOOK_LABEL, hook_argv, root))
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
            Command(
                "ESLint",
                packagemanager.exec_argv(ecosystems.client, "eslint", "--no-cache", "."),
                ecosystems.typescript_root,
            )
        )
    return commands


def selected_eslint_commands(root: Path, paths: Iterable[str], *, label: str = "selected") -> list[Command]:
    return list(select_eslint_commands(root, paths, label=label).commands)


def select_eslint_commands(
    root: Path,
    paths: Iterable[str],
    *,
    label: str = "selected",
    fix: bool = False,
) -> EslintSelection:
    repository = root.resolve()
    fallback_project = _adopted_typescript_project(repository)
    candidates = _selected_eslint_candidates(repository, paths, fallback_project=fallback_project)
    if not candidates:
        return EslintSelection((), 0)
    grouped: dict[Path, set[str]] = {}
    unowned: list[Path] = []
    for candidate in candidates:
        project = _owning_typescript_project(candidate, repository, fallback_project=fallback_project)
        if project is None:
            unowned.append(candidate)
            continue
        grouped.setdefault(project, set()).add(Path(os.path.relpath(candidate, project)).as_posix())
    commands: list[Command] = []
    for project, scoped in sorted(grouped.items(), key=lambda item: str(item[0])):
        install_root = packagemanager.workspace_root(project, repository)
        client = packagemanager.detect(install_root)
        config = _eslint_config(project)
        config_args = () if config is None else ("--config", config.name)
        commands.append(
            Command(
                f"ESLint ({label}: {project.relative_to(repository).as_posix() or '.'})",
                packagemanager.exec_argv(
                    client,
                    "eslint",
                    *config_args,
                    *(("--fix",) if fix else ()),
                    "--",
                    *sorted(scoped),
                ),
                project,
            )
        )
    return EslintSelection(tuple(commands), len(unowned))


def _owning_typescript_project(
    candidate: Path,
    repository: Path,
    *,
    fallback_project: Path | None = None,
) -> Path | None:
    start = candidate if candidate.is_dir() else candidate.parent
    bounded = (start, *(parent for parent in start.parents if parent == repository or repository in parent.parents))
    configured = next((path for path in bounded if _eslint_config(path) is not None), None)
    if configured is not None:
        return configured
    lock_names = tuple(name for name, _client in packagemanager.LOCKFILES)
    locked = next((path for path in bounded if any((path / name).is_file() for name in lock_names)), None)
    if locked is not None:
        return fallback_project if fallback_project is not None and locked == repository else locked
    packaged = next((path for path in bounded if (path / "package.json").is_file()), None)
    if fallback_project is not None and (packaged is None or packaged == repository):
        return fallback_project
    return packaged


def _eslint_config(project: Path) -> Path | None:
    names = ("eslint.config.js", "eslint.config.cjs", "eslint.config.mjs", "eslint.config.ts")
    return next((project / name for name in names if (project / name).is_file()), None)


def _adopted_typescript_project(repository: Path) -> Path | None:
    try:
        adopted = manifest.load(repository)
    except OSError, TypeError, ValueError:
        return None
    if adopted is None:
        return None
    project = (repository / adopted.typescript_dest).resolve()
    return project if project.is_dir() and _eslint_config(project) is not None else None


def staged_eslint_commands(root: Path, paths: Iterable[str]) -> list[Command]:
    return selected_eslint_commands(root, paths, label="staged")


def _selected_eslint_candidates(
    root: Path,
    paths: Iterable[str],
    *,
    fallback_project: Path | None = None,
) -> set[Path]:
    candidates: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        unresolved = path if path.is_absolute() else root / path
        if is_link_like(unresolved):
            continue
        candidate = unresolved.resolve()
        if not candidate.is_relative_to(root):
            continue
        if _is_skill_artifact(candidate, root):
            continue
        if candidate.is_dir() and candidate.name not in _PROJECT_SKIP_DIRS:
            sources = _eslint_sources(candidate)
            owners = {_owning_typescript_project(source, root, fallback_project=fallback_project) for source in sources}
            candidate_owner = _owning_typescript_project(candidate, root, fallback_project=fallback_project)
            if (
                sources
                and owners == {candidate_owner}
                and candidate_owner is not None
                and not _contains_skill_artifacts(candidate)
            ):
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
            name
            for name in directories
            if name not in _PROJECT_SKIP_DIRS
            and not (base.name in _SKILL_ARTIFACT_ROOTS and name == "skills")
            and not is_link_like(base / name)
        ]
        sources.update(
            base / name
            for name in names
            if Path(name).suffix.lower() in _ESLINT_SUFFIXES and not is_link_like(base / name)
        )
    return sources


def _is_skill_artifact(path: Path, repository: Path) -> bool:
    parts = path.relative_to(repository).parts
    return any(root in _SKILL_ARTIFACT_ROOTS and child == "skills" for root, child in pairwise(parts))


def _contains_skill_artifacts(directory: Path) -> bool:
    for parent, directories, _names in os.walk(directory):
        base = Path(parent)
        if base.name in _SKILL_ARTIFACT_ROOTS and "skills" in directories:
            return True
        directories[:] = [
            name for name in directories if name not in _PROJECT_SKIP_DIRS and not is_link_like(base / name)
        ]
    return False


def format_commands(ecosystems: scaffold.Ecosystems) -> list[Command]:
    commands: list[Command] = []
    if ecosystems.python_root is not None:
        for project in _python_verification_roots(ecosystems.python_root):
            commands.extend(
                (
                    Command(
                        "Ruff format",
                        (_environment_binary("ruff"), "format", "."),
                        project,
                    ),
                    Command(
                        "Ruff fixes",
                        (_environment_binary("ruff"), "check", "--fix", "."),
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


def selected_format_commands(root: Path, paths: Iterable[str]) -> list[Command]:
    repository = root.resolve()
    selected = tuple(sorted(set(paths)))
    python_paths = tuple(
        source_path.resolve().relative_to(repository).as_posix()
        for path in selected
        if (source_path := Path(path)).is_file() and source_path.suffix.lower() in {".py", ".pyi"}
    )
    commands: list[Command] = []
    if python_paths:
        commands.extend(
            (
                Command("Ruff format", (_environment_binary("ruff"), "format", *python_paths), repository),
                Command("Ruff fixes", (_environment_binary("ruff"), "check", "--fix", *python_paths), repository),
            )
        )
    commands.extend(select_eslint_commands(repository, selected, label="selected", fix=True).commands)
    return commands


def execute(commands: Iterable[Command]) -> int:
    for command in commands:
        executable = shutil.which(command.argv[0])
        if executable is None:
            sys.stderr.write(f"error: {command.argv[0]} is required for {command.label}\n")
            return 2
        try:
            completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
                [executable, *command.argv[1:]],
                cwd=command.cwd,
                check=False,
                env=_command_environment(command),
                timeout=_COMMAND_TIMEOUT.total_seconds(),
            )
        except subprocess.TimeoutExpired:
            sys.stderr.write(f"error: {command.label} exceeded {_COMMAND_TIMEOUT.total_seconds():g}s and was stopped\n")
            return 2
        if completed.returncode:
            return completed.returncode
        if command.label == _PRECOMMIT_HOOK_LABEL:
            try:
                harden_precommit_hooks(command.cwd)
            except (OSError, subprocess.SubprocessError) as exc:
                sys.stderr.write(f"error: installed pre-commit hook is not durable: {exc}\n")
                return 2
    return 0


def harden_precommit_hooks(root: Path) -> None:
    for hook_type in ("pre-commit", "commit-msg"):
        harden_precommit_hook(root, hook_type=hook_type)


def harden_precommit_hook(root: Path, *, hook_type: str = "pre-commit") -> None:
    hook = _precommit_hook_path(root, hook_type=hook_type)
    text = hook.read_text(encoding="utf-8")
    if _PRECOMMIT_UVX_MARKER in text:
        return
    fallback_point = "elif command -v pre-commit > /dev/null; then"
    if fallback_point not in text:
        msg = f"{hook} does not contain pre-commit's expected launcher fallback"
        raise OSError(msg)
    version = distribution_version("pre-commit")
    fallback = (
        f"{_PRECOMMIT_UVX_MARKER}\n"
        "elif command -v uvx > /dev/null; then\n"
        f'    exec uvx --isolated --python 3.14 --from pre-commit=={version} pre-commit "${{ARGS[@]}}"\n'
    )
    transaction.atomic_write_text(hook.parent, hook, text.replace(fallback_point, fallback + fallback_point, 1))


def _precommit_hook_path(root: Path, *, hook_type: str = "pre-commit") -> Path:
    git = shutil.which("git")
    if git is None:
        msg = "git is required to resolve the installed pre-commit hook"
        raise OSError(msg)
    completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed Git query.
        (git, "rev-parse", "--git-path", f"hooks/{hook_type}"),
        cwd=root,
        check=True,
        capture_output=True,
        env=_git_environment(),
        text=True,
        timeout=_GIT_DISCOVERY_TIMEOUT.total_seconds(),
    )
    resolved = Path(completed.stdout.strip())
    return resolved if resolved.is_absolute() else root / resolved


def _git_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()  # ruff: ignore[banned-api] -- hook-local Git variables must not redirect discovery.
        if name in _GIT_SAFE_ENV
    }


def _command_environment(command: Command) -> dict[str, str] | None:
    _ = command
    environment = os.environ.copy()  # ruff: ignore[banned-api] -- tools must not mistake the isolated runner for the consumer environment.
    environment.pop("VIRTUAL_ENV", None)
    return environment


def verify_custom_rules(root: Path, *, paths: Iterable[str] = (".",)) -> int:
    return runner.run([str(root / path) for path in paths])


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
        msg = f"{name} is missing from the code-standards environment"
        raise OSError(msg)
    return found


def _python_verification_roots(root: Path) -> tuple[Path, ...]:
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
        parsed: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny] -- parser boundary
    except OSError, json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and any(key in parsed for key in ("include", "files"))


def _relative(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    return path.relative_to(root).as_posix() or "."
