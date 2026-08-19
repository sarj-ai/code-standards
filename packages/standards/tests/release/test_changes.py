from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.release.changes import changed_release_targets, pending_release_targets
from sarj_standards.libs.release.process import ProcessFailureError, ProcessResult
from sarj_standards.libs.release.tags import RELEASE_TARGETS


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_standards.libs.release.registry import RegistryRequirement


def _manifests(root: Path) -> None:
    for target in RELEASE_TARGETS.values():
        manifest = root / target.manifest
        manifest.parent.mkdir(parents=True, exist_ok=True)
        contents = '{"version":"1.0.0"}\n' if target.format == "json" else 'version = "1.0.0"\n'
        manifest.write_text(contents, encoding="utf-8")


def test_changed_release_targets_detects_only_manifest_version_lines(tmp_path: Path) -> None:
    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        manifest = argv[-1]
        if manifest == "packages/typescript/package.json":
            return ProcessResult(0, '+  "version": "9.12.0"\n')
        if manifest == "packages/docs-ui/package.json":
            return ProcessResult(0, '+  "version": "0.2.0"\n')
        if manifest == "packages/bootstrap/pyproject.toml":
            return ProcessResult(0, '+version = "1.0.0"\n')
        if manifest == "packages/python/pyproject.toml":
            return ProcessResult(0, '+description = "version unchanged"\n')
        return ProcessResult(0, "")

    changed = changed_release_targets(tmp_path, before="before", after="after", runner=runner)

    assert changed["typescript"] is True
    assert changed["docs-ui"] is True
    assert changed["bootstrap"] is True
    assert changed["python"] is False


def test_changed_release_targets_fails_closed_when_git_diff_fails(tmp_path: Path) -> None:
    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        raise ProcessFailureError(argv, 128)

    with pytest.raises(ProcessFailureError) as raised:
        _ = changed_release_targets(tmp_path, before="missing", after="after", runner=runner)

    assert raised.value.returncode == 128


def test_pending_release_targets_publish_only_current_versions_missing_from_registry(tmp_path: Path) -> None:
    _manifests(tmp_path)
    checked: list[str] = []

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        output = '+version = "2.0.0"\n' if argv[-1] == "packages/standards/pyproject.toml" else ""
        return ProcessResult(0, output)

    def published(requirement: RegistryRequirement) -> bool:
        name = requirement.name
        checked.append(name)
        return name != "sarj-python-lint"

    pending = pending_release_targets(
        tmp_path,
        before="before",
        after="after",
        runner=runner,
        checker=published,
    )

    assert pending["standards"] is False
    assert pending["python"] is True
    assert pending["sql"] is False
    assert "sarj-standards" in checked


def test_pending_release_target_changed_but_already_public_is_a_noop(tmp_path: Path) -> None:
    _manifests(tmp_path)

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        output = '+version = "2.0.0"\n' if argv[-1] == "packages/python/pyproject.toml" else ""
        return ProcessResult(0, output)

    pending = pending_release_targets(
        tmp_path,
        before="before",
        after="after",
        runner=runner,
        checker=lambda _requirement: True,
    )

    assert not any(pending.values())


def test_pending_release_targets_fails_closed_when_registry_lookup_fails(tmp_path: Path) -> None:
    _manifests(tmp_path)

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = argv, cwd, capture_output
        return ProcessResult(0, "")

    def unavailable(_requirement: RegistryRequirement) -> bool:
        message = "registry unavailable"
        raise OSError(message)

    with pytest.raises(OSError, match="registry unavailable"):
        _ = pending_release_targets(
            tmp_path,
            before="before",
            after="after",
            runner=runner,
            checker=unavailable,
        )
