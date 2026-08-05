"""Child commands run independently of the standards package's environment."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from sarj_lint_configs.libs.adoption import lifecycle


if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_execute_removes_parent_virtual_environment_for_nested_uv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    environments: list[dict[str, str] | None] = []

    def which(_name: str) -> str:
        return "/usr/bin/uv"

    def run(
        argv: list[str],
        *,
        cwd: Path,
        check: bool,
        env: dict[str, str] | None,
    ) -> subprocess.CompletedProcess[bytes]:
        del cwd, check
        environments.append(env)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setenv("VIRTUAL_ENV", "/parent/.venv")
    monkeypatch.setattr("sarj_lint_configs.libs.adoption.lifecycle.shutil.which", which)
    monkeypatch.setattr("sarj_lint_configs.libs.adoption.lifecycle.subprocess.run", run)

    status = lifecycle.execute((lifecycle.Command("Python", ("uv", "sync"), tmp_path),))

    assert status == 0
    expected = dict(os.environ)  # ruff: ignore[banned-api] — test the exact environment boundary passed to nested uv.
    expected.pop("VIRTUAL_ENV")
    assert environments == [expected]
