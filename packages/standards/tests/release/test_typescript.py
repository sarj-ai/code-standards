from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import pytest

from sarj_standards.libs.release import pack_typescript, run_typescript_release

from .fakes import FakeTypescriptReleaseRunner as FakeRunner


class _PackageFixture(NamedTuple):
    package: Path
    runner: FakeRunner


def _package(tmp_path: Path) -> _PackageFixture:
    root = tmp_path / "package"
    root.mkdir()
    (root / "package.json").write_text(
        '{"name":"example","version":"1.0.0","main":"./dist/index.js"}',
        encoding="utf-8",
    )
    return _PackageFixture(root, FakeRunner(root))


def test_pack_typescript_uses_argv_and_verifies_archive(tmp_path: Path) -> None:
    package, runner = _package(tmp_path)
    destination = tmp_path / "out"

    result = pack_typescript(package, destination, runner=runner)

    assert result.path == destination.resolve() / "example-1.0.0.tgz"
    assert runner.calls == [
        (
            "npm",
            "pack",
            "--json",
            "--ignore-scripts",
            "--pack-destination",
            str(destination.resolve()),
        )
    ]


def test_pack_typescript_accepts_npm_12_object_manifest(tmp_path: Path) -> None:
    package, _ = _package(tmp_path)
    runner = FakeRunner(package, npm_12_manifest=True)

    result = pack_typescript(package, tmp_path / "out", runner=runner)

    assert result.path.name == "example-1.0.0.tgz"


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
    assert "--ignore-scripts" in runner.calls[4]


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
