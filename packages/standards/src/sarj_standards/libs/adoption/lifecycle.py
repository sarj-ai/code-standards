from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import asdict, dataclass, field, replace
from datetime import timedelta
from functools import partial
from importlib.metadata import version as distribution_version
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- commands are fixed argv assembled from detected ecosystems.
import sys
import tempfile
from typing import TYPE_CHECKING, Final

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting import mobile_tools, runner, security_tools

from . import manifest, packagemanager, scaffold, transaction


if TYPE_CHECKING:
    from collections.abc import Iterable

    from sarj_standards.libs.linting.oxlint import OxlintRequest
    from sarj_standards.libs.linting.policy import Policy


# The Standards capability that runs Oxlint, oxfmt and the tsrs type check.
TYPESCRIPT_CAPABILITY: Final = manifest.TYPESCRIPT_CONFIGS[0]


_PROJECT_SKIP_DIRS = frozenset({".git", ".venv", "build", "dist", "node_modules", "target", "vendor"})
_COMMAND_TIMEOUT = timedelta(minutes=10)
_GIT_DISCOVERY_TIMEOUT = timedelta(seconds=5)
_GIT_SAFE_ENV = frozenset(
    {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "SYSTEMDRIVE", "SYSTEMROOT", "TMPDIR", "XDG_CONFIG_HOME"}
)
_PRECOMMIT_HOOK_LABEL = "pre-commit hooks"
_LEFTHOOK_HOOK_LABEL = "Lefthook repository hooks"
_PRECOMMIT_UVX_MARKER = "# sarj-standards: cache-independent pinned pre-commit fallback"
_MANAGED_UVX_PATH_MARKER = "# sarj-standards: uvx-path"


@dataclass(frozen=True, slots=True)
class Command:
    label: str
    argv: Sequence[str]
    cwd: Path
    # Variables added to the inherited environment.
    environment: tuple[tuple[str, str], ...] = ()
    # Wraps execution, e.g. to write a temporary Oxlint config; yields the argv and cwd to run.
    prepare: Callable[[Command], AbstractContextManager[Command]] | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class Inspection:
    adopted_version: str | None
    profile: manifest.Profile | None
    installed_version: str
    configs: tuple[str, ...]
    python_root: str | None
    typescript_root: str | None
    package_manager: str | None


def package_install(
    label: str,
    root: Path,
    client: packagemanager.PackageManager,
    *,
    workspace: bool,
    yarn: packagemanager.YarnVariant,
) -> Command:
    # Installs exempt exactly the managed versions from the repository's age and trust policies.
    return Command(
        label,
        packagemanager.install_argv(client, workspace=workspace, yarn=yarn),
        root,
        prepare=partial(_exempt_managed_versions, client=client, yarn=yarn),
    )


@contextmanager
def _exempt_managed_versions(
    command: Command, *, client: packagemanager.PackageManager, yarn: packagemanager.YarnVariant
) -> Generator[Command]:
    # Read the policy when the install runs: setup writes the install root's files first.
    exemption = packagemanager.policy_exemption(client, command.cwd, yarn=yarn)
    yield replace(
        command,
        argv=(*command.argv, *exemption.arguments),
        environment=(*command.environment, *exemption.environment),
    )


def install_commands(
    root: Path,
    ecosystems: scaffold.Ecosystems,
    *,
    hook_manager: manifest.HookManager = "pre-commit",
    include_devops: bool = True,
) -> list[Command]:
    commands: list[Command] = []
    adopted = manifest.load_for_setup(root)
    if include_devops:
        from . import devops, doctor  # ruff: ignore[import-outside-top-level] -- setup loads optional native tooling after adoption initialization.

        commands.extend(
            devops.install_commands(
                root,
                doctor.authored_files(root),
                capabilities=adopted.enabled_capabilities if adopted is not None else None,
                prepared=bool(adopted.prepared_targets) if adopted is not None else False,
            )
        )
    commands.extend(_security_install_commands(root, ecosystems, adopted))
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
            package_install(
                "TypeScript peers", install_root, ecosystems.client, workspace=is_workspace, yarn=ecosystems.yarn
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
    if not (git_metadata.is_dir() or git_metadata.is_file()):
        return commands
    if hook_manager == "pre-commit":
        hook_argv = (
            "uvx",
            "--no-config",
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
    elif hook_manager == "lefthook":
        commands.append(
            Command(
                "Lefthook repository hooks",
                (
                    _environment_binary("code-standards"),
                    "--root",
                    str(root),
                    "maintain",
                    "hooks",
                    "install",
                ),
                root,
            )
        )
    return commands


def _has_legacy_in_project_bundle(python_root: Path) -> bool:
    pyproject = python_root / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return re.search(r"(?i)\bsarj[-_]lint[-_]configs\s*(?:\[[^]]+\])?\s*(?:==|>=|<=|~=|!=|>|<|@)", text) is not None


def _security_install_commands(
    root: Path, ecosystems: scaffold.Ecosystems, adopted: manifest.Manifest | None
) -> list[Command]:
    commands: list[Command] = []
    for name in security_tools.TOOLS:
        enabled = ecosystems.actions if name == "zizmor" else ecosystems.infrastructure
        if enabled:
            commands.append(
                Command(f"prepare pinned {name}", (*security_tools.command(name, offline=False), "--version"), root)
            )
    if (ecosystems.swift or ecosystems.kotlin) and (
        adopted is None or "mobile-security" in adopted.enabled_capabilities
    ):
        commands.append(
            Command("prepare pinned semgrep", (*mobile_tools.semgrep_command(offline=False), "--version"), root)
        )
    return commands


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
            _with_tsgolint(
                Command(
                    "Oxlint",
                    packagemanager.exec_argv(ecosystems.client, "oxlint", "--type-check"),
                    ecosystems.typescript_root,
                ),
                ecosystems.typescript_root,
            )
        )
    return commands


def selected_typescript_commands(root: Path, paths: Iterable[str], *, label: str = "selected") -> list[Command]:
    from sarj_standards.libs.linting import oxlint  # ruff: ignore[import-outside-top-level] -- oxlint imports Command from this module.

    return [
        _with_tsgolint(command, root) for command in oxlint.select_oxlint_commands(root, paths, label=label).commands
    ]


def _with_tsgolint(command: Command, root: Path) -> Command:
    from sarj_standards.libs.linting import oxlint  # ruff: ignore[import-outside-top-level] -- oxlint imports Command from this module.

    # Managed configs enable type-aware linting, which needs tsrs-lint even for fixes. Without a local
    # tsrs-lint, Oxlint itself reports the missing executable when the command runs.
    try:
        environment = oxlint.oxlint_environment(command.cwd, root)
    except FileNotFoundError:
        return command
    return replace(command, environment=(*command.environment, *environment.items()))


def format_commands(ecosystems: scaffold.Ecosystems, *, root: Path | None = None) -> list[Command]:
    commands: list[Command] = []
    if ecosystems.python_root is not None:
        for project in _python_verification_roots(ecosystems.python_root):
            commands.extend(
                (
                    Command(
                        "Ruff fixes",
                        (_environment_binary("ruff"), "check", "--fix", "--no-unsafe-fixes", "."),
                        project,
                    ),
                    Command(
                        "Ruff format",
                        (_environment_binary("ruff"), "format", "."),
                        project,
                    ),
                )
            )
    if ecosystems.typescript_root is not None:
        commands.extend(
            (
                _with_tsgolint(
                    Command(
                        "Oxlint fixes",
                        packagemanager.exec_argv(ecosystems.client, "oxlint", "--fix"),
                        ecosystems.typescript_root,
                    ),
                    ecosystems.typescript_root,
                ),
                Command("oxfmt", packagemanager.exec_argv(ecosystems.client, "oxfmt"), ecosystems.typescript_root),
            )
        )
    if root is not None:
        commands.extend(shell_format_commands(root))
    return commands


def selected_format_commands(
    root: Path,
    paths: Iterable[str],
    *,
    trusted: bool = True,
    typescript: bool = True,
    format_only_paths: frozenset[str] = frozenset(),
) -> list[Command]:
    from sarj_standards.libs.linting.policy import Policy  # ruff: ignore[import-outside-top-level] -- fix planning shares checking policy.

    repository = root.resolve()
    adopted = manifest.load(repository)
    policy = Policy.from_manifest(repository, adopted)
    selected = tuple(sorted(set(policy.filter_paths(paths))))
    commands: list[Command] = []
    if adopted is None or "ruff" in adopted.enabled_capabilities:
        lint_paths = tuple(path for path in selected if policy.relative(path) not in format_only_paths)
        commands.extend(_ruff_fix_commands(repository, lint_paths, policy))
    if trusted and typescript and (adopted is None or TYPESCRIPT_CAPABILITY in adopted.enabled_capabilities):
        lint_paths = tuple(path for path in selected if policy.relative(path) not in format_only_paths)
        commands.extend(oxlint_fix_commands(repository, lint_paths, policy))
        commands.extend(oxfmt_write_commands(repository, selected))
    commands.extend(shell_format_commands(repository, selected))
    return commands


def _ruff_fix_commands(root: Path, paths: Sequence[str], policy: Policy) -> list[Command]:
    from sarj_standards.libs.linting.external import (  # ruff: ignore[import-outside-top-level] -- defer the checking adapter to avoid its lifecycle command dependency during import.
        ruff_config_arguments,
        ruff_project_groups,
    )

    sources: list[str] = []
    for path in paths:
        source = Path(path)
        source = source if source.is_absolute() else root / source
        if source.is_file() and source.suffix.lower() in {".py", ".pyi"}:
            sources.append(str(source.resolve()))
    groups: dict[tuple[Path, Path | None, frozenset[str]], list[str]] = {}
    for project, config, scoped in ruff_project_groups(sources, root):
        for path in scoped:
            key = (project, config, policy.excluded_rule_ids(path, "ruff"))
            groups.setdefault(key, []).append(Path(os.path.relpath(path, project)).as_posix())
    commands: list[Command] = []
    for (project, config, disabled), group in sorted(
        groups.items(), key=lambda item: (str(item[0][0]), str(item[0][1]), sorted(item[0][2]))
    ):
        ignored = ("--extend-ignore", ",".join(sorted(disabled))) if disabled else ()
        config_args = ruff_config_arguments(config)
        commands.extend(
            (
                Command(
                    "Ruff fixes",
                    (
                        _environment_binary("ruff"),
                        "check",
                        "--fix",
                        "--no-unsafe-fixes",
                        *config_args,
                        *ignored,
                        "--",
                        *group,
                    ),
                    project,
                ),
                Command("Ruff format", (_environment_binary("ruff"), "format", *config_args, "--", *group), project),
            )
        )
    return commands


def oxlint_fix_commands(
    root: Path, paths: Sequence[str], policy: Policy, *, include_config_sources: bool = False
) -> list[Command]:
    from sarj_standards.libs.linting import oxlint  # ruff: ignore[import-outside-top-level] -- oxlint imports Command from this module.

    repository = root.resolve()
    commands: list[Command] = []
    for command in oxlint.select_oxlint_commands(
        repository, paths, fix=True, include_config_sources=include_config_sources
    ).commands:
        # The directive step below removes unused directives; reporting them here would be noise.
        quiet = replace(
            command, argv=oxlint.with_options(command.argv, "--report-unused-disable-directives-severity=off")
        )
        commands.append(
            replace(
                _with_tsgolint(quiet, repository),
                prepare=partial(oxlint.selected_config, request=oxlint_exclusions(command, policy)),
            )
        )
    if commands:
        commands.append(_unused_directive_command(repository, paths))
    return commands


def oxlint_exclusions(command: Command, policy: Policy) -> OxlintRequest:
    # `-A` does not reach JS plugin rules, so per-path excluded rules go through the overlay
    # config, whose override globs are relative to the consumer config.
    from sarj_standards.libs.linting import oxlint  # ruff: ignore[import-outside-top-level] -- oxlint imports Command from this module.
    from sarj_standards.libs.repository import rule_catalog_artifact  # ruff: ignore[import-outside-top-level] -- distinguish custom selectors from upstream Oxlint IDs.

    custom = rule_catalog_artifact.selector_index().canonical
    base = oxlint.config_directory(command)
    grouped: dict[frozenset[str], list[str]] = {}
    for path in sorted(oxlint.command_files(command)):
        disabled = frozenset(
            f"@sarj/{rule}" if f"oxlint:{rule}" in custom else oxlint.canonical_rule_id(rule)
            for rule in policy.excluded_rule_ids(path, "oxlint")
        )
        if disabled:
            grouped.setdefault(disabled, []).append(_literal_glob(Path(os.path.relpath(path, base)).as_posix()))
    ordered = sorted(grouped.items(), key=lambda item: sorted(item[0]))
    return oxlint.OxlintRequest(forced={}, disabled=tuple((tuple(files), rules) for rules, files in ordered))


def _literal_glob(path: str) -> str:
    # Next.js routes such as `app/[id]/page.tsx` must not become character classes.
    return re.sub(r"[][*?{}]", lambda match: f"[{match[0]}]", path)


def _unused_directive_command(root: Path, paths: Sequence[str]) -> Command:
    # `oxlint --fix` never removes unused directives; Oxlint's own report drives the edit.
    return Command(
        "Oxlint unused directives",
        (
            _environment_binary("python"),
            "-m",
            "sarj_standards.libs.linting.oxlint_directives",
            "--root",
            str(root),
        ),
        root,
        prepare=partial(_directive_paths_file, paths=paths),
    )


@contextmanager
def _directive_paths_file(command: Command, *, paths: Sequence[str]) -> Generator[Command]:
    from sarj_standards.libs.linting.oxlint_directives import MAX_PATH_BYTES  # ruff: ignore[import-outside-top-level] -- the worker owns its bounded path transport.

    if any("\0" in path for path in paths):
        msg = "directive path transport cannot contain NUL in a filename"
        raise ValueError(msg)
    if sum(len(os.fsencode(path)) + 1 for path in paths) > MAX_PATH_BYTES:
        msg = "directive path selection exceeds the transport byte budget"
        raise ValueError(msg)
    payload = b"".join(os.fsencode(path) + b"\0" for path in paths)
    with tempfile.TemporaryDirectory(prefix="sarj-directive-paths-") as directory:
        source = Path(directory) / "paths"
        source.write_bytes(payload)
        yield replace(command, argv=(*command.argv, "--paths-file", str(source)))


def oxfmt_write_commands(root: Path, paths: Sequence[str]) -> list[Command]:
    from sarj_standards.libs.linting import oxfmt  # ruff: ignore[import-outside-top-level] -- oxfmt imports this module.

    projects: dict[Path, list[str]] = {}
    for path in paths:
        project = oxfmt.project_for(Path(path), root)
        if project is not None:
            projects.setdefault(project, []).append(path)
    return [oxfmt.write_command(scoped, project=project, root=root) for project, scoped in sorted(projects.items())]


def shell_format_commands(root: Path, paths: Iterable[str] | None = None) -> list[Command]:
    from sarj_standards.libs.linting import shell_format  # ruff: ignore[import-outside-top-level] -- only fix operations need shell source detection.
    from sarj_standards.libs.linting.policy import Policy  # ruff: ignore[import-outside-top-level] -- reuse adoption path exclusions.

    from . import devops, doctor, manifest  # ruff: ignore[import-outside-top-level] -- shared source discovery avoids another tree walker.

    adopted = manifest.load(root)
    if adopted is not None and "shfmt" not in adopted.enabled_capabilities:
        return []
    policy = Policy.from_manifest(root, adopted)
    selected = doctor.authored_files(root) if paths is None else tuple(Path(path) for path in paths)
    shells = tuple(
        str(path)
        for path in selected
        if policy.allows_path(path)
        and policy.allows_rule(shell_format.format_diagnostic(path=policy.relative(path), source="", formatted=""))
        and devops.has_shell_input(path, policy.relative(path))
    )
    if not shells:
        return []
    return [
        Command(
            "Shell format",
            (
                _environment_binary("python"),
                "-m",
                "sarj_standards.libs.linting.shell_format",
                "--root",
                str(root),
                *shells,
            ),
            root,
        )
    ]


def execute(commands: Iterable[Command], *, stdout_to_stderr: bool = False) -> int:
    for command in commands:
        executable = shutil.which(command.argv[0])
        if executable is None:
            sys.stderr.write(f"error: {command.argv[0]} is required for {command.label}\n")
            return 2
        hook_transaction: transaction.FileTransaction | None = None
        try:
            if command.label in {_PRECOMMIT_HOOK_LABEL, _LEFTHOOK_HOOK_LABEL}:
                hook_transaction = _capture_hook_transaction(
                    command.cwd, lefthook=command.label == _LEFTHOOK_HOOK_LABEL
                )
            with nullcontext(command) if command.prepare is None else command.prepare(command) as prepared:
                completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- pass the fixed executable as an argv sequence with shell execution disabled.
                    [executable, *prepared.argv[1:]],
                    cwd=prepared.cwd,
                    check=False,
                    env={**_command_environment(), **dict(prepared.environment)},
                    timeout=_COMMAND_TIMEOUT.total_seconds(),
                    stdout=2 if stdout_to_stderr else None,
                )
        except subprocess.TimeoutExpired as exc:
            _report_hook_rollback(hook_transaction)
            sys.stderr.write(f"error: {command.label} exceeded {exc.timeout:g}s and was stopped\n")
            return 2
        except BaseException:
            _report_hook_rollback(hook_transaction)
            raise
        if completed.returncode:
            _report_hook_rollback(hook_transaction)
            return completed.returncode
        if command.label == _PRECOMMIT_HOOK_LABEL:
            try:
                harden_precommit_hooks(command.cwd)
            except (OSError, subprocess.SubprocessError) as exc:
                _report_hook_rollback(hook_transaction)
                sys.stderr.write(f"error: installed pre-commit hook is not durable: {exc}\n")
                return 2
    return 0


def _capture_hook_transaction(root: Path, *, lefthook: bool = False) -> transaction.FileTransaction:
    if lefthook:
        from sarj_standards.libs.repository import hooks as repository_hooks  # ruff: ignore[import-outside-top-level] -- load the selected manager's resolved hook ownership only for Lefthook installation.

        return repository_hooks.capture_transaction(root)
    hooks_dir = _precommit_hook_path(root).parent
    names = (
        "pre-commit",
        "pre-commit.legacy",
        "commit-msg",
        "commit-msg.legacy",
        "pre-push",
        "pre-push.legacy",
        ".sarj-lefthook",
        ".sarj-lefthook.exe",
    )
    paths = tuple(hooks_dir / name for name in names)
    transaction.validate_targets(hooks_dir, paths)
    return transaction.FileTransaction.capture(hooks_dir, paths)


def _report_hook_rollback(hook_transaction: transaction.FileTransaction | None) -> None:
    if hook_transaction is None:
        return
    if detail := hook_transaction.rollback().render():
        sys.stderr.write(f"error: {detail}\n")


def harden_precommit_hooks(root: Path) -> None:
    for hook_type in ("pre-commit", "commit-msg"):
        harden_precommit_hook(root, hook_type=hook_type)


def harden_precommit_hook(root: Path, *, hook_type: str = "pre-commit") -> None:
    hook = _precommit_hook_path(root, hook_type=hook_type)
    text = hook.read_text(encoding="utf-8")
    uvx = shutil.which("uvx", path=os.environ.get("PATH", ""))  # ruff: ignore[banned-api] -- persist setup-time path for GUI Git clients.
    if uvx is None:
        msg = "uvx is required to harden managed pre-commit hooks"
        raise OSError(msg)
    lines = [line for line in text.splitlines() if _MANAGED_UVX_PATH_MARKER not in line]
    uvx_path = f'export PATH={shlex.quote(Path(uvx).parent.as_posix())}:"$PATH" {_MANAGED_UVX_PATH_MARKER}'
    lines.insert(1, uvx_path)
    hardened = "\n".join(lines) + "\n"
    if _PRECOMMIT_UVX_MARKER not in hardened:
        fallback_point = "elif command -v pre-commit > /dev/null; then"
        if fallback_point not in hardened:
            msg = f"{hook} does not contain pre-commit's expected launcher fallback"
            raise OSError(msg)
        version = distribution_version("pre-commit")
        fallback = (
            f"{_PRECOMMIT_UVX_MARKER}\n"
            "elif command -v uvx > /dev/null; then\n"
            f'    exec uvx --no-config --isolated --python 3.15 --from pre-commit=={version} pre-commit "${{ARGS[@]}}"\n'
        )
        hardened = hardened.replace(fallback_point, fallback + fallback_point, 1)
    transaction.atomic_write_text(hook.parent, hook, hardened)


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


def _command_environment() -> dict[str, str]:
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
        parsed: object = parse_json(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and any(key in parsed for key in ("include", "files"))


def _relative(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    return path.relative_to(root).as_posix() or "."
