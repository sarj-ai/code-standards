from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
import shutil
import tempfile
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from sarj_standards.libs.linting.devops_tools import (
    NativeTool,
    NativeToolError,
    checked_runtime_tool,
    checked_tool,
    invoke,
)
from sarj_standards.libs.linting.prepared_devops import (
    MAX_MANIFEST_BYTES,
    contained_file,
    verify_artifact_hash,
)


if TYPE_CHECKING:
    from collections.abc import Mapping

    from sarj_standards.libs.diagnostics import Diagnostic
    from sarj_standards.libs.linting.external import ProcessRunner

type NativeKind = Literal["systemd", "nginx", "kamailio", "prometheus-config", "prometheus-rules", "compose"]
_MAX_CLOSURE_BYTES: Final = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _Profile:
    program: str
    version_args: tuple[str, ...]
    version_pattern: str
    version_stderr: bool = False


_PROFILES: Final = {
    "systemd": _Profile("systemd-analyze", ("--version",), r"^(?P<version>systemd [^\r\n]+)$"),
    "nginx": _Profile("nginx", ("-v",), r"^(?P<version>nginx version: nginx/[^\r\n]+)$", version_stderr=True),
    "kamailio": _Profile("kamailio", ("-V",), r"^(?P<version>version: kamailio [^\r\n]+)$"),
    "prometheus-config": _Profile("promtool", ("--version",), r"^(?P<version>promtool, version [^\r\n]+)$"),
    "prometheus-rules": _Profile("promtool", ("--version",), r"^(?P<version>promtool, version [^\r\n]+)$"),
}


class _NativeConfig(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    kind: NativeKind
    native_version: str = Field(min_length=1)
    manifests: list[str] = Field(min_length=1)
    artifacts: dict[str, str]
    executables: list[str] = Field(default_factory=list)
    environment_file: str | None = Field(default=None, min_length=1)


def validate_native(
    directory: Path,
    target: Mapping[str, object],
    *,
    root: Path,
    runner: ProcessRunner,
    trust_repository_code: bool,
) -> tuple[Diagnostic, ...]:
    config = _NativeConfig.model_validate(target)
    if not trust_repository_code:
        message = "Native service configuration validation requires explicit trusted repository code"
        raise ValueError(message)
    tool = _native_tool(config, root=root, runner=runner)
    with tempfile.TemporaryDirectory(prefix="sarj-native-config-") as temporary:
        work = Path(temporary)
        _stage(directory, config, work)
        try:
            invoke(tool, _arguments(config, work), root=work, runner=runner)
        except NativeToolError as error:
            message = str(error).replace(str(work), "<prepared>")
            message = re.sub(r"(?m)^\s*\d+\(\d+\)\s*", "", message)
            raise NativeToolError(message) from error
    return ()


def _native_tool(config: _NativeConfig, *, root: Path, runner: ProcessRunner) -> NativeTool:
    if config.kind == "compose":
        tool = checked_tool("docker", root=root, runner=runner, expected_version=config.native_version)
        return replace(tool, finding_exits=frozenset())
    profile = _PROFILES[config.kind]
    return checked_runtime_tool(
        NativeTool(
            profile.program,
            config.native_version,
            profile.version_args,
            profile.version_pattern,
            finding_exits=frozenset(),
            version_stderr=profile.version_stderr,
        ),
        root=root,
        runner=runner,
    )


def _stage(directory: Path, config: _NativeConfig, work: Path) -> None:
    if set(config.executables) - config.artifacts.keys():
        message = "prepared executables require artifact hashes"
        raise ValueError(message)
    total = 0
    for name, digest in config.artifacts.items():
        source = contained_file(directory, name)
        total += source.stat().st_size
        if total > _MAX_CLOSURE_BYTES or (name in config.manifests and source.stat().st_size > MAX_MANIFEST_BYTES):
            message = "native configuration exceeds the prepared input size bounds"
            raise ValueError(message)
        destination = work / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        verify_artifact_hash(destination, digest)
        destination.chmod(0o755 if name in config.executables else 0o644)


def _arguments(config: _NativeConfig, work: Path) -> tuple[str, ...]:
    paths = tuple(str(work / name) for name in config.manifests)
    if config.kind == "compose":
        if config.environment_file is None or config.environment_file not in config.artifacts:
            message = "Prepared Compose requires a hashed environment_file"
            raise ValueError(message)
        files = tuple(argument for path in paths for argument in ("-f", path))
        return ("compose", "--env-file", str(work / config.environment_file), *files, "config", "--quiet")
    if config.kind == "systemd":
        return (
            f"--root={work}",
            "--generators=no",
            "--man=no",
            "--recursive-errors=yes",
            "verify",
            *("/" + name for name in config.manifests),
        )
    if config.kind in {"nginx", "kamailio"}:
        if len(paths) != 1:
            message = f"{config.kind} requires one entry configuration; stage includes as artifacts"
            raise ValueError(message)
        if config.kind == "nginx":
            (work / "logs").mkdir(exist_ok=True)
            return ("-t", "-p", str(work) + "/", "-c", paths[0], "-e", "stderr")
        (work / "run").mkdir(exist_ok=True)
        return ("-E", "-Y", str(work / "run"), "-w", str(work), "-c", "-f", paths[0])
    return ("check", config.kind.removeprefix("prometheus-"), *paths)
