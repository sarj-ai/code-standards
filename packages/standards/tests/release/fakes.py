from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import tarfile
from typing import TYPE_CHECKING, final

from sarj_standards.libs.release import ProcessResult


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


@final
class FakeRolloutRunner:
    def __init__(self, responses: list[tuple[int, str]] | None = None) -> None:
        self.responses: list[tuple[int, str]] = list(responses or [])
        self.commands: list[tuple[str, ...]] = []
        self.environments: list[Mapping[str, str] | None] = []
        self.working_directories: list[Path | None] = []

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        rendered = tuple(command)
        self.commands.append(rendered)
        self.environments.append(env)
        self.working_directories.append(cwd)
        returncode, stdout = self.responses.pop(0) if self.responses else (0, "")
        result = subprocess.CompletedProcess(rendered, returncode, stdout, "")
        if check and returncode:
            raise subprocess.CalledProcessError(returncode, rendered, output=stdout)
        return result


class FakeTypescriptReleaseRunner:
    package_root: Path
    npm_12_manifest: bool

    def __init__(self, package_root: Path, *, npm_12_manifest: bool = False) -> None:
        self.package_root = package_root
        self.npm_12_manifest = npm_12_manifest
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        capture_output: bool = False,
    ) -> ProcessResult:
        del capture_output
        assert cwd == self.package_root
        self.calls.append(argv)
        if argv[:2] != ("npm", "pack"):
            return ProcessResult(0)
        destination = Path(argv[-1])
        archive = destination / "example-1.0.0.tgz"
        contents = b"export {};"
        with tarfile.open(archive, "w:gz") as package:
            license_info = tarfile.TarInfo("package/LICENSE")
            license_info.size = 3
            package.addfile(license_info, io.BytesIO(b"MIT"))
            manifest = b'{"name":"example","version":"1.0.0"}'
            manifest_info = tarfile.TarInfo("package/package.json")
            manifest_info.size = len(manifest)
            package.addfile(manifest_info, io.BytesIO(manifest))
            info = tarfile.TarInfo("package/dist/index.js")
            info.size = len(contents)
            package.addfile(info, io.BytesIO(contents))
        artifact = {"filename": archive.name, "files": [{"path": "dist/index.js"}]}
        report = {"example": artifact} if self.npm_12_manifest else [artifact]
        return ProcessResult(0, f"build output\n{json.dumps(report)}\n")
