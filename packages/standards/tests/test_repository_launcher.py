from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import launcher


if TYPE_CHECKING:
    from pathlib import Path


def test_repository_wiring_is_stable_across_bundle_versions() -> None:
    command = launcher.repository_command("check", ".")

    assert "sarj-standards==" not in command
    assert ".sarj/standards check ." in command
    assert "5.14.1" not in launcher.repository_script()


def test_repository_launcher_rejects_invalid_manifest_before_resolution(tmp_path: Path) -> None:
    path = tmp_path / launcher.REPOSITORY_LAUNCHER
    path.parent.mkdir()
    path.write_text(launcher.repository_script(), encoding="utf-8")
    (tmp_path / ".sarj-standards.toml").write_text('schema = 3\nbundle = "latest; bad"\n', encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(path), "check"], check=False, capture_output=True, text=True, shell=False
    )

    assert completed.returncode == 2
    assert "exact canonical release" in completed.stderr


def test_repository_launcher_accepts_only_the_current_manifest_schema(tmp_path: Path) -> None:
    path = tmp_path / launcher.REPOSITORY_LAUNCHER
    path.parent.mkdir()
    path.write_text(launcher.repository_script(), encoding="utf-8")
    (tmp_path / ".sarj-standards.toml").write_text('schema = 4\nbundle = "5.14.1"\n', encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(path), "check"], check=False, capture_output=True, text=True, shell=False
    )

    assert completed.returncode == 2
    assert "unsupported manifest schema 4" in completed.stderr


def test_exact_launcher_rejects_noncanonical_version() -> None:
    with pytest.raises(ValueError, match="invalid exact"):
        launcher.argv(version="latest")
