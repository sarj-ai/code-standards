"""Package release detection is library-owned, not embedded shell."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs.libs.release.changes import changed_release_targets
from sarj_lint_configs.libs.release.process import ProcessFailureError, ProcessResult


if TYPE_CHECKING:
    from pathlib import Path


def test_changed_release_targets_detects_only_manifest_version_lines(tmp_path: Path) -> None:
    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        manifest = argv[-1]
        if manifest == "packages/typescript/package.json":
            return ProcessResult(0, '+  "version": "9.12.0"\n')
        if manifest == "packages/python/pyproject.toml":
            return ProcessResult(0, '+description = "version unchanged"\n')
        return ProcessResult(0, "")

    changed = changed_release_targets(tmp_path, before="before", after="after", runner=runner)

    assert changed["typescript"] is True
    assert changed["python"] is False


def test_changed_release_targets_fails_closed_when_git_diff_fails(tmp_path: Path) -> None:
    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        raise ProcessFailureError(argv, 128)

    with pytest.raises(ProcessFailureError) as raised:
        _ = changed_release_targets(tmp_path, before="missing", after="after", runner=runner)

    assert raised.value.returncode == 128
