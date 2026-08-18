from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


def test_importing_cli_does_not_eagerly_load_command_implementations() -> None:
    script = (
        "import sys; import sarj_standards.__main__; "
        "blocked = {'sarj_standards.doctor', 'sarj_standards.lifecycle', "
        "'sarj_standards.repository', 'sarj_standards.runner'}; "
        "raise SystemExit(1 if blocked & sys.modules.keys() else 0)"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_update_parser_exposes_the_complete_bundle_controls() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sarj_standards", "update", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--no-install" in result.stdout


def test_invalid_destination_uses_usage_error_exit_status(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sarj_standards", "--root", str(tmp_path / "missing"), "doctor"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "is not a directory" in result.stderr


def test_root_is_one_explicit_global_option(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sarj_standards",
            "--root",
            str(tmp_path),
            "doctor",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode in {0, 1}
    assert "unrecognized arguments" not in result.stderr
