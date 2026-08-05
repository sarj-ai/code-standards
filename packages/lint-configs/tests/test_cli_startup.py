"""The command router should not load every implementation on startup."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from pathlib import Path


def test_importing_cli_does_not_eagerly_load_command_implementations() -> None:
    script = (
        "import sys; import sarj_lint_configs.__main__; "
        "blocked = {'sarj_lint_configs.doctor', 'sarj_lint_configs.lifecycle', "
        "'sarj_lint_configs.repository', 'sarj_lint_configs.runner'}; "
        "raise SystemExit(1 if blocked & sys.modules.keys() else 0)"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_upgrade_parser_accepts_config_only_mode() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "upgrade", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--no-install" in result.stdout


def test_invalid_destination_uses_usage_error_exit_status(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sarj_lint_configs", "doctor", "--dest", str(tmp_path / "missing")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "is not a directory" in result.stderr
