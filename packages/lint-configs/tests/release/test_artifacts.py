from __future__ import annotations

import io
import json
import tarfile
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs.libs.release import (
    required_artifact_paths,
    verify_built_package,
    verify_package_tarball,
)


if TYPE_CHECKING:
    from pathlib import Path


def _tarball(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, contents in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(contents)
            archive.addfile(info, io.BytesIO(contents))


def test_required_artifact_paths_flattens_conditional_exports_in_order() -> None:
    package = {
        "main": "./dist/index.js",
        "types": "./dist/index.d.ts",
        "exports": {
            ".": {"types": "./dist/index.d.ts", "import": "./dist/index.js"},
            "./strict": "./dist/strict.js",
        },
    }

    assert required_artifact_paths(package) == (
        "dist/index.js",
        "dist/index.d.ts",
        "dist/strict.js",
    )


@pytest.mark.parametrize("entry", ["../secret", "/absolute", "dist/../secret", "./"])
def test_required_artifact_paths_rejects_unsafe_entries(entry: str) -> None:
    with pytest.raises(ValueError, match="unsafe exported entry point"):
        required_artifact_paths({"main": entry})


def test_verify_built_package_checks_nonempty_dist_files(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"main": "./dist/index.js", "types": "./dist/index.d.ts"}),
        encoding="utf-8",
    )
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/index.js").write_text("export {};", encoding="utf-8")
    (tmp_path / "dist/index.d.ts").write_text("export {};", encoding="utf-8")

    assert verify_built_package(tmp_path) == ("dist/index.js", "dist/index.d.ts")


def test_verify_package_tarball_reads_actual_archive(tmp_path: Path) -> None:
    archive = tmp_path / "package.tgz"
    _tarball(archive, {"package/LICENSE": b"MIT", "package/dist/index.js": b"export {};"})

    assert verify_package_tarball(archive, ("dist/index.js",)) == ("dist/index.js",)


@pytest.mark.parametrize(
    ("files", "pattern"),
    [
        ({"../escape": b"bad", "package/dist/index.js": b"export {};"}, "unsafe path"),
        (
            {"package/dist/index.js": b"export {};", "package/dist/index.js.map": b"{}"},
            "source maps are forbidden",
        ),
    ],
    ids=["traversal", "source-map"],
)
def test_verify_package_tarball_rejects_unsafe_content(tmp_path: Path, files: dict[str, bytes], pattern: str) -> None:
    archive = tmp_path / "package.tgz"
    _tarball(archive, files)

    with pytest.raises(ValueError, match=pattern):
        verify_package_tarball(archive, ("dist/index.js",))


def test_verify_package_tarball_rejects_an_empty_export(tmp_path: Path) -> None:
    archive = tmp_path / "package.tgz"
    _tarball(archive, {"package/dist/index.js": b""})

    with pytest.raises(ValueError, match="empty"):
        verify_package_tarball(archive, ("dist/index.js",))


def test_verify_package_tarball_rejects_install_lifecycle_scripts(tmp_path: Path) -> None:
    archive = tmp_path / "package.tgz"
    manifest = json.dumps({"scripts": {"postinstall": "node payload.js"}}).encode()
    _tarball(
        archive,
        {
            "package/LICENSE": b"MIT",
            "package/package.json": manifest,
            "package/dist/index.js": b"export {};",
        },
    )

    with pytest.raises(ValueError, match="install lifecycle script is forbidden"):
        verify_package_tarball(archive, ("dist/index.js",))


def test_verify_package_tarball_binds_name_and_version(tmp_path: Path) -> None:
    archive = tmp_path / "package.tgz"
    manifest = json.dumps({"name": "@sarj/eslint-plugin", "version": "9.12.1"}).encode()
    _tarball(
        archive,
        {
            "package/LICENSE": b"MIT",
            "package/package.json": manifest,
            "package/dist/index.js": b"export {};",
        },
    )

    assert verify_package_tarball(
        archive,
        ("dist/index.js",),
        expected_name="@sarj/eslint-plugin",
        expected_version="9.12.1",
    ) == ("dist/index.js",)
    with pytest.raises(ValueError, match="name does not match"):
        verify_package_tarball(
            archive,
            ("dist/index.js",),
            expected_name="@sarj/tsconfig",
            expected_version="9.12.1",
        )
