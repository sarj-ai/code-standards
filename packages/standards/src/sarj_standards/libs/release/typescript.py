"""Reusable TypeScript check, pack, and publish operations."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Literal

from sarj_standards.libs.release._values import is_object_dict, is_object_list, string_object_dict
from sarj_standards.libs.release.artifacts import (
    load_package_json,
    required_artifact_paths,
    verify_package_tarball,
)
from sarj_standards.libs.release.process import (
    ProcessResult,
    ProcessRunner,
    run_build_process,
    run_process,
    run_process_environment,
)


if TYPE_CHECKING:
    from collections.abc import Mapping


ReleaseMode = Literal["check", "pack", "publish"]


@dataclass(frozen=True, slots=True)
class PackedArtifact:
    """A verified npm package artifact."""

    path: Path
    included_files: tuple[str, ...]


def pack_typescript(
    package_root: Path,
    destination: Path,
    *,
    runner: ProcessRunner = run_build_process,
) -> PackedArtifact:
    """Create and independently verify an npm tarball."""
    destination.mkdir(parents=True, exist_ok=True)
    result = runner(
        (
            "npm",
            "pack",
            "--json",
            "--ignore-scripts",
            "--pack-destination",
            str(destination.resolve()),
        ),
        cwd=package_root,
        capture_output=True,
    )
    report = _npm_pack_report(result.stdout)
    filename = report.get("filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        msg = "npm pack returned an invalid artifact manifest"
        raise ValueError(msg)
    included = _included_paths(report.get("files"))
    package_manifest = load_package_json(package_root)
    required = required_artifact_paths(package_manifest)
    if not required:
        msg = "package.json declares no publishable entry points"
        raise ValueError(msg)
    missing_report = next((path for path in required if path not in included), None)
    if missing_report is not None:
        msg = f"npm pack report omits exported entry point: {missing_report}"
        raise ValueError(msg)
    tarball = destination.resolve() / filename
    name = package_manifest.get("name")
    version = package_manifest.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        msg = "package.json must declare string name and version fields"
        raise TypeError(msg)
    verify_package_tarball(tarball, required, expected_name=name, expected_version=version)
    return PackedArtifact(tarball, included)


def _npm_pack_report(output: str) -> dict[str, object]:
    decoder = json.JSONDecoder()
    reports: list[dict[str, object]] = []
    for index, character in enumerate(output):
        if character != "[":
            continue
        try:
            candidate: object
            candidate, _ = decoder.raw_decode(output[index:])  # pyright: ignore[reportAny]
        except json.JSONDecodeError:
            continue
        report = _as_pack_report(candidate)
        if report is not None:
            reports.append(report)
    if not reports:
        msg = "npm pack returned no artifact manifest"
        raise ValueError(msg)
    return reports[-1]


def _as_pack_report(value: object) -> dict[str, object] | None:
    if not is_object_list(value) or not value or not is_object_dict(value[0]):
        return None
    report = string_object_dict(value[0], label="npm pack report")
    return report if "filename" in report and "files" in report else None


def _included_paths(value: object) -> tuple[str, ...]:
    if not is_object_list(value):
        msg = "npm pack returned an invalid files manifest"
        raise TypeError(msg)
    included: list[str] = []
    for item in value:
        if not is_object_dict(item):
            continue
        path = string_object_dict(item, label="npm pack file").get("path")
        if isinstance(path, str):
            included.append(path)
    return tuple(included)


def check_typescript(package_root: Path, *, runner: ProcessRunner = run_build_process) -> None:
    """Run the reproducible TypeScript release test sequence."""
    for argv in (
        ("npm", "ci", "--no-audit", "--no-fund"),
        ("npm", "run", "lint"),
        ("npm", "run", "typecheck"),
        ("npm", "test"),
    ):
        runner(argv, cwd=package_root)


def run_typescript_release(
    mode: ReleaseMode,
    package_root: Path,
    *,
    destination: Path | None = None,
    runner: ProcessRunner = run_process,
    environment: Mapping[str, str] | None = None,
) -> PackedArtifact | None:
    """Check, pack, or publish the TypeScript package without shell execution."""
    if mode not in {"check", "pack", "publish"}:
        msg = f"unsupported TypeScript release mode: {mode}"
        raise ValueError(msg)
    build_runner = run_build_process if runner is run_process else runner
    if mode == "pack":
        if destination is None:
            msg = "pack mode requires a destination directory"
            raise ValueError(msg)
        return pack_typescript(package_root, destination, runner=build_runner)
    if destination is not None:
        msg = f"{mode} mode does not accept a destination directory"
        raise ValueError(msg)
    check_typescript(package_root, runner=build_runner)
    with TemporaryDirectory(prefix="sarj-typescript-release-") as temporary:
        artifact = pack_typescript(package_root, Path(temporary), runner=build_runner)
        if mode == "publish":
            publish_runner = runner
            if runner is run_process and environment is not None:

                def publish_runner(
                    argv: tuple[str, ...],
                    *,
                    cwd: Path,
                    capture_output: bool = False,
                ) -> ProcessResult:
                    return run_process_environment(
                        argv,
                        cwd=cwd,
                        capture_output=capture_output,
                        environment=environment,
                    )

            publish_runner(
                ("npm", "publish", str(artifact.path), "--access", "public", "--ignore-scripts"),
                cwd=package_root,
            )
    return None
