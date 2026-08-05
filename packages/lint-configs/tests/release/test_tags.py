from __future__ import annotations

from pathlib import Path

import pytest

from sarj_lint_configs.libs.release import (
    RELEASE_TARGETS,
    ProcessFailureError,
    ProcessResult,
    ReleaseTarget,
    create_release_tags,
    missing_remote_release_tags,
    validate_release_tag,
)


def test_validate_release_tag_reads_json(tmp_path: Path) -> None:
    manifest = tmp_path / "package.json"
    manifest.write_text('{"version":"1.2.3"}', encoding="utf-8")

    result = validate_release_tag(
        "typescript-v1.2.3",
        tmp_path,
        targets={"typescript": ReleaseTarget(Path("package.json"), "json")},
    )

    assert result.version == "1.2.3"
    assert result.manifest == Path("package.json")


def test_validate_release_tag_reads_toml(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "2.0.0"\n', encoding="utf-8")

    result = validate_release_tag(
        "python-v2.0.0",
        tmp_path,
        targets={"python": ReleaseTarget(Path("pyproject.toml"), "toml")},
    )

    assert result.target == "python"


@pytest.mark.parametrize("tag", ["", "unknown-v1.0.0", "python-1.0.0", "python-v1.0.0/evil"])
def test_validate_release_tag_rejects_unknown_or_unsafe_tags(tmp_path: Path, tag: str) -> None:
    with pytest.raises(ValueError, match="unrecognized release tag"):
        validate_release_tag(tag, tmp_path, targets={"python": ReleaseTarget(Path("pyproject.toml"), "toml")})


def test_validate_release_tag_rejects_version_drift(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('version = "2.0.0"\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"does not match .* version 2\.0\.0"):
        validate_release_tag(
            "python-v1.0.0",
            tmp_path,
            targets={"python": ReleaseTarget(Path("pyproject.toml"), "toml")},
        )


def _write_release_manifests(root: Path) -> None:
    for target in RELEASE_TARGETS.values():
        manifest = root / target.manifest
        manifest.parent.mkdir(parents=True, exist_ok=True)
        contents = '{"version":"1.2.3"}' if target.format == "json" else '[project]\nversion = "1.2.3"\n'
        manifest.write_text(contents, encoding="utf-8")


def test_missing_remote_release_tags_derives_names_from_manifests(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if argv[-1] == "refs/tags/python-v1.2.3":
            return ProcessResult(0)
        raise ProcessFailureError(argv, 2)

    missing = missing_remote_release_tags(tmp_path, runner=runner)

    assert "python-v1.2.3" not in missing
    assert "typescript-v1.2.3" in missing
    assert len(missing) == 5


def test_create_release_tags_is_idempotent_and_pushes_exact_ref(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        calls.append(argv)
        if argv[:2] == ("git", "ls-remote"):
            raise ProcessFailureError(argv, 2)
        if argv[:3] == ("git", "rev-parse", "--verify"):
            raise ProcessFailureError(argv, 1)
        return ProcessResult(0)

    result = create_release_tags(tmp_path, ("python", "python"), runner=runner)

    assert result.created == ("python-v1.2.3",)
    assert ("git", "tag", "-a", "python-v1.2.3", "-m", "python 1.2.3") in calls
    assert calls[-1] == ("git", "push", "origin", "refs/tags/python-v1.2.3")


def test_remote_tag_network_failure_is_not_misreported_as_missing(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        raise ProcessFailureError(argv, 128)

    with pytest.raises(ProcessFailureError):
        missing_remote_release_tags(tmp_path, runner=runner)
