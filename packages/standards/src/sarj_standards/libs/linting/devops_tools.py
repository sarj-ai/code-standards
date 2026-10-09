from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
import shutil
import stat
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- catch bounded version-query failures.
import sys
from types import MappingProxyType
from typing import Final

from sarj_standards.libs.json_boundary import parse_json
from sarj_standards.libs.linting.external import ProcessOutput, ProcessRunner, run_process
from sarj_standards.libs.typed_containers import is_object_mapping


@dataclass(frozen=True, slots=True)
class NativeTool:
    name: str
    version: str
    version_args: tuple[str, ...]
    version_pattern: str
    finding_exits: frozenset[int] = frozenset({1})
    executable: Path | None = None
    standalone_compose: bool = False


TOOLS: Final = MappingProxyType(
    {
        tool.name: tool
        for tool in (
            NativeTool("helm", "3.19.0", ("version", "--short"), r"^v(?P<version>\d+\.\d+\.\d+)"),
            NativeTool("kubeconform", "0.8.0", ("-v",), r"^v?(?P<version>\d+\.\d+\.\d+)"),
            NativeTool("kube-linter", "0.8.3", ("version",), r"v?(?P<version>\d+\.\d+\.\d+)"),
            NativeTool("shfmt", "3.14.1", ("--version",), r"^v(?P<version>\d+\.\d+\.\d+)"),
            NativeTool("shellcheck", "0.11.0", ("--version",), r"^version:\s*(?P<version>\d+\.\d+\.\d+)"),
            NativeTool("actionlint", "1.7.12", ("-version",), r"^(?P<version>\d+\.\d+\.\d+)"),
            NativeTool("hadolint", "2.15.1", ("--version",), r"v?(?P<version>\d+\.\d+\.\d+)"),
            NativeTool("terraform", "1.15.8", ("version",), r"Terraform v(?P<version>\d+\.\d+\.\d+)"),
            NativeTool(
                "tflint", "0.63.1", ("--version",), r"TFLint version (?P<version>\d+\.\d+\.\d+)", frozenset({2})
            ),
            NativeTool(
                "docker",
                "5.1.2",
                ("compose", "version", "--format", "json"),
                r'"version"\s*:\s*"v?(?P<version>\d+\.\d+\.\d+)"',
            ),
        )
    }
)


class NativeToolError(ValueError):
    pass


MISE_REFS: Final = MappingProxyType(
    {
        "helm": "aqua:helm/helm",
        "kubeconform": "aqua:yannh/kubeconform",
        "kube-linter": "aqua:stackrox/kube-linter",
        "shfmt": "aqua:mvdan/sh",
        "shellcheck": "aqua:koalaman/shellcheck",
        "actionlint": "aqua:rhysd/actionlint",
        "hadolint": "aqua:hadolint/hadolint",
        "terraform": "aqua:hashicorp/terraform",
        "tflint": "aqua:terraform-linters/tflint",
        "docker": "github:docker/compose",
    }
)


def checked_tool(
    name: str, *, root: Path, runner: ProcessRunner = run_process, expected_version: str | None = None
) -> NativeTool:
    tool = TOOLS[name]
    if expected_version is not None:
        if (
            name != "docker"
            or re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", expected_version) is None
        ):
            message = "Only Compose accepts a consumer-specific exact semantic version"
            raise NativeToolError(message)
        tool = replace(tool, version=expected_version)
    # Injected runners implement the native-tool protocol directly. Production
    # resolves an immutable absolute executable before attesting its version.
    if runner is not run_process:
        return _attest(tool, root=root, runner=runner)
    adjacent = Path(sys.executable).parent / name
    path_binary = shutil.which(name)
    candidates = (str(adjacent), path_binary) if adjacent.is_file() else (path_binary,)
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            executable = Path(candidate).resolve(strict=True)
            return _attest(replace(tool, executable=executable), root=root, runner=runner)
        except OSError, NativeToolError:
            pass
    installed = _mise_tool(tool, root=root, runner=runner)
    return _attest(installed, root=root, runner=runner)


def _attest(tool: NativeTool, *, root: Path, runner: ProcessRunner) -> NativeTool:
    output = runner(_argv(tool, tool.version_args), cwd=root)
    actual = _version(tool, output.stdout)
    if output.returncode or actual != tool.version:
        msg = f"{tool.name} {actual} is installed; exact version {tool.version} is required"
        raise NativeToolError(msg)
    return tool


def _version(tool: NativeTool, source: str) -> str:
    if tool.name == "docker":
        value = parse_json(source)
        if not is_object_mapping(value) or set(value) != {"version"} or not isinstance(value.get("version"), str):
            message = "Compose version protocol must contain exactly one version string"
            raise NativeToolError(message)
    matches = tuple(re.finditer(tool.version_pattern, source, re.MULTILINE))
    return matches[0].group("version") if len(matches) == 1 else "unknown"


def installed_compose_version(root: Path, *, runner: ProcessRunner = run_process) -> str | None:
    executable = shutil.which("docker") if runner is run_process else "docker"
    if executable is None:
        return None
    try:
        output = runner((executable, *TOOLS["docker"].version_args), cwd=root)
        payload = parse_json(output.stdout)
    except OSError, ValueError, subprocess.SubprocessError:
        return None
    if output.returncode or not is_object_mapping(payload):
        return None
    version = payload.get("version")
    if not isinstance(version, str):
        return None
    exact = version.removeprefix("v")
    return exact if re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", exact) is not None else None


def _mise_tool(tool: NativeTool, *, root: Path, runner: ProcessRunner) -> NativeTool:
    mise = shutil.which("mise")
    if mise is None:
        msg = f"{tool.name} {tool.version} is missing; run explicit setup to install pinned native tools"
        raise NativeToolError(msg)
    output = runner(
        (mise, "--no-config", "--no-env", "--no-hooks", "where", f"{MISE_REFS[tool.name]}@{tool.version}"), cwd=root
    )
    lines = output.stdout.strip().splitlines()
    if output.returncode or len(lines) != 1 or not Path(lines[0]).is_absolute():
        msg = f"mise has no unambiguous installed {tool.name} {tool.version}; run explicit setup"
        raise NativeToolError(msg)
    installation = Path(lines[0]).resolve(strict=True)
    binary = "docker-compose" if tool.name == "docker" else tool.name
    candidates: set[Path] = set()
    for relative in (binary, f"bin/{binary}"):
        candidate = installation / relative
        if not candidate.exists():
            continue
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(installation)
        if stat.S_ISREG(resolved.stat().st_mode):
            candidates.add(resolved)
    if len(candidates) != 1:
        msg = f"mise's installed {tool.name} does not expose one regular native executable"
        raise NativeToolError(msg)
    return replace(tool, executable=candidates.pop(), standalone_compose=tool.name == "docker")


def _argv(tool: NativeTool, args: tuple[str, ...]) -> tuple[str, ...]:
    prefix = str(tool.executable) if tool.executable is not None else tool.name
    arguments = args[1:] if tool.standalone_compose and args[:1] == ("compose",) else args
    return (prefix, *arguments)


def invoke(
    tool: NativeTool, args: tuple[str, ...], *, root: Path, runner: ProcessRunner = run_process
) -> ProcessOutput:
    output = runner(_argv(tool, args), cwd=root)
    if output.returncode not in {0, *tool.finding_exits}:
        msg = f"{tool.name} failed with exit {output.returncode}: {output.stderr.strip()}"
        raise NativeToolError(msg)
    return output
