from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- only catch bounded native runner failures.
from typing import TYPE_CHECKING

from . import manifest
from .doctor import Finding


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sarj_standards.libs.linting.external import ProcessRunner

    from .lifecycle import Command


@dataclass(frozen=True, slots=True)
class ToolsSetupResult:
    status: int
    findings: tuple[Finding, ...]


def required_tools(
    root: Path, files: Sequence[Path], *, capabilities: Sequence[str] | None = None, prepared: bool = False
) -> tuple[str, ...]:
    capabilities = manifest.DEVOPS_ANALYZERS if capabilities is None else capabilities
    selected = frozenset(capabilities)
    names: set[str] = set()
    for path in files:
        names.update(_file_tools(path, path.relative_to(root).as_posix(), selected))
    if prepared:
        names.update({"helm", "kubeconform", "kube-linter"})
    return tuple(sorted(names))


def _file_tools(path: Path, relative: str, selected: frozenset[str]) -> set[str]:
    names: set[str] = set()
    if path.suffix in {".yaml", ".yml"} and ".github/workflows/" in relative:
        names.update(selected & {"actionlint"})
        if "actionlint" in selected:
            names.add("shellcheck")
    name = path.name.lower()
    if (
        not name.endswith(".dockerignore")
        and (name == "dockerfile" or name.startswith("dockerfile.") or name.endswith(".dockerfile"))
        and "hadolint" in selected
    ):
        names.add("hadolint")
    if path.suffix == ".tf" or path.name.endswith(".tf.json"):
        names.update(selected & {"terraform", "tflint"})
    if (
        path.name in {"compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml"}
        and "compose" in selected
    ):
        names.add("docker")
    if not selected.isdisjoint({"shellcheck", *manifest.DEVOPS_ANALYZERS}) and _has_shell_input(path, relative):
        names.add("shfmt")
    return names


def _has_shell_input(path: Path, relative: str) -> bool:
    from sarj_standards.libs.linting.devops_programs import ProgramProjectionError, execution_blocks  # ruff: ignore[import-outside-top-level] -- reuse semantic config selection without parsing a shell program.

    if path.suffix.lower() in {".sh", ".bash"}:
        return True
    try:
        return any(block.source for block in execution_blocks(relative, path.read_text(encoding="utf-8")))
    except OSError, UnicodeDecodeError, ProgramProjectionError:
        return False


def install_commands(
    root: Path,
    files: Sequence[Path],
    *,
    capabilities: Sequence[str] | None = None,
    prepared: bool = False,
    compose_version: str | None = None,
) -> tuple[Command, ...]:
    from sarj_standards.libs.linting.devops_tools import MISE_REFS, TOOLS  # ruff: ignore[import-outside-top-level] -- avoid lifecycle/native runner initialization cycle.

    from .lifecycle import Command  # ruff: ignore[import-outside-top-level] -- setup resolves command contracts after module initialization.

    names = required_tools(root, files, capabilities=capabilities, prepared=prepared)
    if "docker" in names and compose_version is None:
        adopted = manifest.load_for_setup(root)
        compose_version = None if adopted is None else adopted.compose_version
    names = tuple(name for name in names if name != "docker" or compose_version is not None)
    if not names:
        return ()
    tools = tuple(f"{MISE_REFS[name]}@{compose_version if name == 'docker' else TOOLS[name].version}" for name in names)
    commands = [
        Command(
            "Pinned native DevOps tools", ("mise", "--no-config", "--no-env", "--no-hooks", "install", *tools), root
        )
    ]
    if "tflint" in names:
        config = Path(__file__).resolve().parents[2] / "configs" / "tflint.strict.hcl"
        commands.append(
            Command(
                "Pinned TFLint Google plugin",
                (
                    "mise",
                    "--no-config",
                    "--no-env",
                    "--no-hooks",
                    "exec",
                    f"{MISE_REFS['tflint']}@{TOOLS['tflint'].version}",
                    "--",
                    "tflint",
                    "--config",
                    str(config),
                    "--init",
                ),
                root,
            )
        )
    return tuple(commands)


def health_findings(root: Path, files: Sequence[Path], *, runner: ProcessRunner | None = None) -> tuple[Finding, ...]:
    from sarj_standards.libs.linting.devops_tools import TOOLS, checked_tool  # ruff: ignore[import-outside-top-level] -- read-only doctor checks start after adoption modules initialize.
    from sarj_standards.libs.linting.external import run_process  # ruff: ignore[import-outside-top-level] -- reuse bounded native runner.

    from .doctor import Finding, Level  # ruff: ignore[import-outside-top-level] -- doctor record boundary avoids recursive module imports.

    try:
        adopted = manifest.load(root)
    except OSError, TypeError, ValueError:
        return ()
    if adopted is None:
        return ()
    names = required_tools(
        root, files, capabilities=adopted.enabled_capabilities, prepared=bool(adopted.prepared_targets)
    )
    findings: list[Finding] = []
    for name in names:
        try:
            _require_compose_pin(name, adopted.compose_version)
            checked_tool(
                name,
                root=root,
                runner=run_process if runner is None else runner,
                expected_version=adopted.compose_version if name == "docker" else None,
            )
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            findings.append(
                Finding(
                    Level.DRIFT,
                    name,
                    str(error),
                    f"doctor.devops.{name}.version",
                    "run explicit `code-standards setup` to install pinned native tools",
                )
            )
        else:
            findings.append(
                Finding(
                    Level.OK,
                    name,
                    f"Native {name} {adopted.compose_version if name == 'docker' else TOOLS[name].version} is attested",
                    f"doctor.devops.{name}.version",
                )
            )
    return tuple(findings)


def _require_compose_pin(name: str, version: str | None) -> None:
    if name == "docker" and version is None:
        message = "Compose requires explicit manifest [devops].compose_version"
        raise ValueError(message)


def setup_tools_only(root: Path) -> ToolsSetupResult:
    from . import doctor, lifecycle  # ruff: ignore[import-outside-top-level] -- explicit installation starts after adoption initialization.

    root = root.resolve()
    adopted = manifest.load(root)
    if adopted is None:
        message = "tools-only setup requires an existing current-schema standards manifest"
        raise ValueError(message)
    files = doctor.authored_files(root)
    names = required_tools(
        root, files, capabilities=adopted.enabled_capabilities, prepared=bool(adopted.prepared_targets)
    )
    for name in names:
        _require_compose_pin(name, adopted.compose_version)
    commands = install_commands(
        root,
        files,
        capabilities=adopted.enabled_capabilities,
        prepared=bool(adopted.prepared_targets),
        compose_version=adopted.compose_version,
    )
    status = lifecycle.execute(commands)
    if status:
        return ToolsSetupResult(status, ())
    findings = health_findings(root, files)
    return ToolsSetupResult(1 if any(finding.level is doctor.Level.DRIFT for finding in findings) else 0, findings)
