from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile

import pytest

from sarj_lint_configs.libs.release import ProcessResult, pack_typescript, run_typescript_release


class FakeRunner:
    package_root: Path

    def __init__(self, package_root: Path) -> None:
        self.package_root = package_root
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
        report = [{"filename": archive.name, "files": [{"path": "dist/index.js"}]}]
        return ProcessResult(0, f"build output\n{json.dumps(report)}\n")


def _package(tmp_path: Path) -> tuple[Path, FakeRunner]:
    root = tmp_path / "package"
    root.mkdir()
    (root / "package.json").write_text(
        '{"name":"example","version":"1.0.0","main":"./dist/index.js"}',
        encoding="utf-8",
    )
    return root, FakeRunner(root)


def test_pack_typescript_uses_argv_and_verifies_archive(tmp_path: Path) -> None:
    package, runner = _package(tmp_path)
    destination = tmp_path / "out"

    result = pack_typescript(package, destination, runner=runner)

    assert result.path == destination.resolve() / "example-1.0.0.tgz"
    assert runner.calls == [("npm", "pack", "--json", "--pack-destination", str(destination.resolve()))]


def test_check_mode_runs_clean_checks_then_pack(tmp_path: Path) -> None:
    package, runner = _package(tmp_path)

    run_typescript_release("check", package, runner=runner)

    assert runner.calls[:4] == [
        ("npm", "ci", "--no-audit", "--no-fund"),
        ("npm", "run", "lint"),
        ("npm", "run", "typecheck"),
        ("npm", "test"),
    ]
    assert runner.calls[4][:2] == ("npm", "pack")


def test_publish_delegates_authentication_to_npm_for_oidc(tmp_path: Path) -> None:
    package, runner = _package(tmp_path)

    run_typescript_release("publish", package, runner=runner, environment={})

    assert runner.calls[-1][0:2] == ("npm", "publish")


def test_publish_uses_verified_tarball_and_disables_scripts(tmp_path: Path) -> None:
    package, runner = _package(tmp_path)

    run_typescript_release("publish", package, runner=runner, environment={"NPM_TOKEN": "configured"})

    assert runner.calls[-1][0:2] == ("npm", "publish")
    assert runner.calls[-1][-3:] == ("--access", "public", "--ignore-scripts")


def test_pack_mode_requires_destination(tmp_path: Path) -> None:
    package, runner = _package(tmp_path)

    with pytest.raises(ValueError, match="requires a destination"):
        run_typescript_release("pack", package, runner=runner)


def test_release_library_rejects_invalid_runtime_mode(tmp_path: Path) -> None:
    package, runner = _package(tmp_path)

    with pytest.raises(ValueError, match="unsupported TypeScript release mode"):
        run_typescript_release("invalid", package, runner=runner)  # pyright: ignore[reportArgumentType]

    assert runner.calls == []
