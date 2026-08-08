"""Publish one validated package target through its native client."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

from sarj_standards.libs.release.artifacts import verify_python_wheel_license
from sarj_standards.libs.release.process import ProcessRunner, run_build_process, run_process
from sarj_standards.libs.release.typescript import run_typescript_release


if TYPE_CHECKING:
    from collections.abc import Mapping


PublishTarget = Literal["typescript", "python", "sql", "iac", "standards", "tsconfig"]
_EXPECTED_PYTHON_ARTIFACTS = 1
_PYTHON_TARGETS: Mapping[str, str] = MappingProxyType(
    {
        "python": "python",
        "sql": "sql",
        "iac": "iac",
        "standards": "standards",
    }
)


def publish_target(root: Path, target: PublishTarget, *, runner: ProcessRunner = run_process) -> None:
    """Build and publish exactly one package without shell commands or globs."""
    resolved = root.resolve()
    build_runner = run_build_process if runner is run_process else runner
    if target == "typescript":
        _ = run_typescript_release("publish", resolved / "packages" / "typescript", runner=runner)
        return
    if target == "tsconfig":
        cwd = resolved / "packages" / "tsconfig"
        with TemporaryDirectory(prefix="sarj-tsconfig-release-") as temporary:
            destination = Path(temporary)
            result = build_runner(
                ("npm", "pack", "--json", "--pack-destination", str(destination)),
                cwd=cwd,
                capture_output=True,
            )
            artifact = destination / _npm_pack_filename(result.stdout)
            if not artifact.is_file() or artifact.stat().st_size == 0:
                msg = f"npm pack did not create its reported artifact: {artifact.name}"
                raise ValueError(msg)
            runner(("npm", "publish", str(artifact), "--access", "public", "--ignore-scripts"), cwd=cwd)
        return
    package = _PYTHON_TARGETS.get(target)
    if package is None:
        msg = f"unsupported release target: {target}"
        raise ValueError(msg)
    cwd = resolved / "packages" / package
    with TemporaryDirectory(prefix=f"sarj-{package}-release-") as temporary:
        destination = Path(temporary)
        build_runner(("uv", "build", "--wheel", "--out-dir", str(destination)), cwd=cwd)
        artifacts = tuple(sorted(destination.glob("*.whl")))
        if len(artifacts) != _EXPECTED_PYTHON_ARTIFACTS or any(
            not artifact.is_file() or artifact.stat().st_size == 0 for artifact in artifacts
        ):
            msg = f"uv build did not create exactly one wheel for {target}"
            raise ValueError(msg)
        verify_python_wheel_license(artifacts[0])
        runner(("uv", "publish", *(str(artifact) for artifact in artifacts)), cwd=cwd)


def _npm_pack_filename(output: str) -> str:
    """Extract the safe tarball filename from npm's JSON pack report."""
    decoder = json.JSONDecoder()
    for index in range(len(output) - 1, -1, -1):
        if output[index] != "[":
            continue
        try:
            report, _ = decoder.raw_decode(output[index:])  # pyright: ignore[reportAny]
        except json.JSONDecodeError:
            continue
        if not isinstance(report, list) or not report or not isinstance(report[0], dict):
            continue
        filename = report[0].get("filename")  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        if isinstance(filename, str) and Path(filename).name == filename and filename.endswith(".tgz"):
            return filename
    msg = "npm pack returned no safe artifact filename"
    raise ValueError(msg)
