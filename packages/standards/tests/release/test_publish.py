"""Native package publication is planned by the release library."""

from __future__ import annotations

import json
from pathlib import Path
import zipfile

from sarj_standards.libs.release import ProcessResult, publish_target


def test_python_publish_builds_then_publishes_without_shell(tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], Path]] = []

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = capture_output
        calls.append((argv, cwd))
        if argv[:2] == ("uv", "build"):
            destination = Path(argv[-1])
            with zipfile.ZipFile(destination / "example-1.0.0-py3-none-any.whl", "w") as wheel:
                wheel.writestr("example-1.0.0.dist-info/licenses/LICENSE", "MIT")
        return ProcessResult(0)

    publish_target(tmp_path, "python", runner=runner)

    build, publish = calls
    assert build[0][:3] == ("uv", "build", "--wheel")
    assert build[0][3] == "--out-dir"
    assert publish[0][:2] == ("uv", "publish")
    assert {Path(path).name for path in publish[0][2:]} == {"example-1.0.0-py3-none-any.whl"}
    assert build[1] == publish[1] == tmp_path / "packages" / "python"


def test_tsconfig_publish_uses_exact_native_command(tmp_path: Path) -> None:
    calls: list[tuple[tuple[str, ...], Path]] = []

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = capture_output
        calls.append((argv, cwd))
        if argv[:2] == ("npm", "pack"):
            destination = Path(argv[-1])
            (destination / "example-1.0.0.tgz").write_bytes(b"archive")
            return ProcessResult(0, json.dumps([{"filename": "example-1.0.0.tgz"}]))
        return ProcessResult(0)

    publish_target(tmp_path, "tsconfig", runner=runner)

    pack, publish = calls
    assert pack[0][:3] == ("npm", "pack", "--json")
    assert publish[0][0:2] == ("npm", "publish")
    assert Path(publish[0][2]).name == "example-1.0.0.tgz"
    assert publish[0][-3:] == ("--access", "public", "--ignore-scripts")
    assert pack[1] == publish[1] == tmp_path / "packages" / "tsconfig"
