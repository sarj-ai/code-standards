from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from sarj_standards.libs.release import (
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
        if argv[:3] == ("git", "rev-parse", "--verify") and argv[-1].startswith("refs/tags/"):
            raise ProcessFailureError(argv, 1)
        return ProcessResult(0)

    result = create_release_tags(
        tmp_path,
        ("python", "python"),
        commit="publish-sha",
        runner=runner,
        publication_checker=lambda _requirement: True,
    )

    assert result.created == ("python-v1.2.3",)
    assert ("git", "tag", "-a", "python-v1.2.3", "publish-sha", "-m", "python 1.2.3") in calls
    assert calls[-1] == ("git", "push", "origin", "refs/tags/python-v1.2.3")


def test_create_release_tags_rejects_an_unpublished_manifest_version(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        calls.append(argv)
        if argv[:3] == ("git", "rev-parse", "--verify"):
            return ProcessResult(0)
        raise ProcessFailureError(argv, 2)

    with pytest.raises(ValueError, match=r"pypi publication is unavailable: sarj-python-lint@1\.2\.3"):
        create_release_tags(
            tmp_path,
            ("python",),
            commit="publish-sha",
            runner=runner,
            publication_checker=lambda _requirement: False,
            attempts=1,
        )

    assert calls == [
        ("git", "rev-parse", "--verify", "publish-sha^{commit}"),
        ("git", "ls-remote", "--exit-code", "--tags", "origin", "refs/tags/python-v1.2.3"),
    ]


def test_create_release_tags_retries_registry_propagation(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)
    calls: list[tuple[str, ...]] = []
    checks = iter((False, False, True))
    sleeps: list[float] = []

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        calls.append(argv)
        if argv[:3] == ("git", "rev-parse", "--verify") and argv[-1] == "publish-sha^{commit}":
            return ProcessResult(0, "published-commit\n")
        if argv[:3] == ("git", "rev-parse", "--verify") and argv[-1].startswith("refs/tags/"):
            raise ProcessFailureError(argv, 1)
        if argv[:2] == ("git", "ls-remote"):
            raise ProcessFailureError(argv, 2)
        return ProcessResult(0, "")

    result = create_release_tags(
        tmp_path,
        ("python",),
        commit="publish-sha",
        runner=runner,
        publication_checker=lambda _requirement: next(checks),
        attempts=3,
        delay=timedelta(seconds=2),
        sleeper=sleeps.append,
    )

    assert result.created == ("python-v1.2.3",)
    assert sleeps == [2.0, 2.0]


def test_create_release_tags_rejects_an_existing_tag_on_another_commit(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if argv[:3] == ("git", "rev-parse", "--verify"):
            return ProcessResult(0, "published-commit\n")
        if argv[-1] == "refs/tags/python-v1.2.3":
            return ProcessResult(0)
        if argv[-1] == "refs/tags/python-v1.2.3^{}":
            return ProcessResult(
                0,
                "tag-object\trefs/tags/python-v1.2.3\ndifferent-commit\trefs/tags/python-v1.2.3^{}\n",
            )
        raise AssertionError(argv)

    with pytest.raises(ValueError, match="not publishing commit published-commit"):
        create_release_tags(
            tmp_path,
            ("python",),
            commit="publish-sha",
            runner=runner,
            publication_checker=lambda _requirement: True,
        )


def test_create_release_tags_rejects_a_local_tag_on_another_commit(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if argv[-1] == "publish-sha^{commit}":
            return ProcessResult(0, "published-commit\n")
        if argv[:2] == ("git", "ls-remote"):
            raise ProcessFailureError(argv, 2)
        if argv[-1] == "refs/tags/python-v1.2.3^{commit}":
            return ProcessResult(0, "different-commit\n")
        raise AssertionError(argv)

    with pytest.raises(ValueError, match=r"existing local tag .* not publishing commit published-commit"):
        create_release_tags(
            tmp_path,
            ("python",),
            commit="publish-sha",
            runner=runner,
            publication_checker=lambda _requirement: True,
        )


def test_remote_tag_network_failure_is_not_misreported_as_missing(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        raise ProcessFailureError(argv, 128)

    with pytest.raises(ProcessFailureError):
        missing_remote_release_tags(tmp_path, runner=runner)
