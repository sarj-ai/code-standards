"""Release causality ties shipped changes to their authoritative versions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_lint_configs.libs.release.causality import check_release_causality
from sarj_lint_configs.libs.release.process import ProcessResult


if TYPE_CHECKING:
    from pathlib import Path


def test_publishable_source_change_without_version_bump_fails(tmp_path: Path) -> None:
    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(0, "packages/python/src/sarj_python_lint/api.py\0")
        return ProcessResult(0, "")

    report = check_release_causality(tmp_path, before="base", after="head", runner=runner)

    assert not report.ok
    assert report.changed_targets == ("python",)
    assert report.violations[0].target == "python"


def test_matching_manifest_bump_satisfies_source_change(tmp_path: Path) -> None:
    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(
                0,
                "packages/python/src/sarj_python_lint/api.py\0packages/python/pyproject.toml\0",
            )
        if argv[-1] == "packages/python/pyproject.toml":
            return ProcessResult(0, '+version = "0.50.0"\n')
        return ProcessResult(0, "")

    report = check_release_causality(tmp_path, before="base", after="head", runner=runner)

    assert report.ok
    assert report.bumped_targets == ("python",)


def test_tests_and_lockfiles_do_not_force_noop_releases(tmp_path: Path) -> None:
    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(
                0,
                "packages/python/tests/test_api.py\0packages/python/uv.lock\0",
            )
        return ProcessResult(0, "")

    report = check_release_causality(tmp_path, before="base", after="head", runner=runner)

    assert report.ok
    assert not report.changed_targets
