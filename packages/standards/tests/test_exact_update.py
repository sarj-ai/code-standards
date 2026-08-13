"""Exact-version updates cannot race a newer registry release."""

from __future__ import annotations

import shutil
import subprocess
from typing import TYPE_CHECKING

import sarj_standards.cli.main as cli


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class _Completed:
    returncode: int = 0


def test_update_to_bootstraps_the_exact_requested_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def find_uvx(_name: str) -> str:
        return "/opt/uvx"

    monkeypatch.delenv("SARJ_STANDARDS_BOOTSTRAPPED", raising=False)
    monkeypatch.setattr(shutil, "which", find_uvx)

    def run(command: list[str], **kwargs: object) -> _Completed:
        observed["command"] = command
        observed["environment"] = kwargs["env"]
        return _Completed()

    monkeypatch.setattr(subprocess, "run", run)

    status = cli.main(["--root", str(tmp_path), "update", "--to", "5.7.1", "--check"])

    assert status == 0
    command = observed["command"]
    assert isinstance(command, list)
    assert "sarj-standards==5.7.1" in command
    assert command[-3:] == ["--to", "5.7.1", "--check"]
    assert "--offline" not in command
    environment = observed["environment"]
    assert isinstance(environment, dict)
    assert environment["SARJ_STANDARDS_BOOTSTRAPPED"] == "1"


def test_exact_inner_update_rejects_an_executing_version_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SARJ_STANDARDS_BOOTSTRAPPED", "1")

    status = cli.main(["--root", str(tmp_path), "update", "--to", "999.0.0"])

    assert status == 2
    assert "executing bundle is" in capsys.readouterr().err


def test_exact_update_rejects_noncanonical_versions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = cli.main(["--root", str(tmp_path), "update", "--to", "05.07.01"])

    assert status == 2
    assert "must be canonical" in capsys.readouterr().err
