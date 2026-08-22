from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import subprocess

import pytest

from sarj_standards.libs.release import (
    RELEASE_TARGETS,
    ProcessFailureError,
    ProcessResult,
    ReleaseTarget,
    ReleaseTargetId,
    create_release_tags,
    missing_remote_release_tags,
    validate_release_tag,
    verify_remote_release_tags,
)


def test_release_target_ids_are_the_authoritative_manifest_keys() -> None:
    assert tuple(RELEASE_TARGETS) == tuple(ReleaseTargetId)
    assert RELEASE_TARGETS[ReleaseTargetId.PYTHON] == RELEASE_TARGETS["python"]


def test_release_target_id_rejects_unknown_packages() -> None:
    with pytest.raises(ValueError, match="is not a valid ReleaseTargetId"):
        _ = ReleaseTargetId("unknown")


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
    compatibility = root / "packages/standards-compat/pyproject.toml"
    compatibility.parent.mkdir(parents=True, exist_ok=True)
    compatibility.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


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
    assert len(missing) == 6


def test_verify_remote_release_tags_accepts_exact_and_unchanged_existing_tags(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)
    exact = "a" * 40
    older = "b" * 40

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if argv[:3] == ("git", "rev-parse", "--verify"):
            revision = argv[-1]
            resolved = older if revision == f"{older}^{{commit}}" else exact
            return ProcessResult(0, stdout=f"{resolved}\n")
        if argv[:2] == ("git", "ls-remote") and len(argv) == 7:
            tag = argv[-2].removesuffix("^{}")
            target = tag.removeprefix("refs/tags/").split("-v", 1)[0]
            actual = older if target == "python" else exact
            return ProcessResult(
                0,
                stdout=f"{actual}\t{tag}\n{actual}\t{tag}^{{}}\n",
            )
        if argv[:2] == ("git", "ls-remote"):
            return ProcessResult(0)
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            return ProcessResult(0)
        if argv[:3] == ("git", "diff", "--quiet"):
            return ProcessResult(0)
        raise AssertionError(argv)

    assert verify_remote_release_tags(tmp_path, commit="publish-sha", runner=runner) == ()


def test_verify_remote_release_tags_rejects_wrong_existing_tag_tree(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)
    exact = "a" * 40
    wrong = "b" * 40

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if argv[:3] == ("git", "rev-parse", "--verify"):
            revision = argv[-1]
            resolved = wrong if revision == f"{wrong}^{{commit}}" else exact
            return ProcessResult(0, stdout=f"{resolved}\n")
        if argv[:2] == ("git", "ls-remote") and len(argv) == 7:
            tag = argv[-2].removesuffix("^{}")
            return ProcessResult(0, stdout=f"{wrong}\t{tag}^{{}}\n")
        if argv[:2] == ("git", "ls-remote"):
            return ProcessResult(0)
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            return ProcessResult(0)
        if argv[:3] == ("git", "diff", "--quiet"):
            raise ProcessFailureError(argv, 1)
        raise AssertionError(argv)

    with pytest.raises(ValueError, match=r"existing remote tag typescript-v1\.2\.3 points to"):
        verify_remote_release_tags(tmp_path, commit="publish-sha", runner=runner)


def test_verify_remote_release_tags_rejects_tag_that_does_not_peel_to_a_commit(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)
    exact = "a" * 40
    tree = "b" * 40

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if argv[:3] == ("git", "rev-parse", "--verify"):
            if argv[-1] == f"{tree}^{{commit}}":
                raise ProcessFailureError(argv, 128)
            return ProcessResult(0, stdout=f"{exact}\n")
        if argv[:2] == ("git", "ls-remote") and len(argv) == 7:
            tag = argv[-2]
            return ProcessResult(0, stdout=f"{tree}\t{tag}^{{}}\n")
        if argv[:2] == ("git", "ls-remote"):
            return ProcessResult(0)
        raise AssertionError(argv)

    with pytest.raises(ValueError, match="does not resolve to a commit"):
        verify_remote_release_tags(tmp_path, commit="publish-sha", runner=runner)


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
    assert (
        "git",
        "-c",
        "user.name=sarj-ai release automation",
        "-c",
        "user.email=release-automation@sarj.ai",
        "tag",
        "-a",
        "python-v1.2.3",
        "publish-sha",
        "-m",
        "python 1.2.3",
    ) in calls
    assert calls[-1] == ("git", "push", "origin", "refs/tags/python-v1.2.3")


def test_create_release_tags_handles_real_git_missing_tag_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_environment = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    for key in local_environment:
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
    repository = tmp_path / "repository"
    remote = tmp_path / "remote.git"
    repository.mkdir()
    _write_release_manifests(repository)
    _git(repository, "init")
    _git(repository, "add", ".")
    _git(
        repository,
        "-c",
        "user.email=release-test@example.com",
        "-c",
        "user.name=Release Test",
        "commit",
        "-m",
        "release",
    )
    _git(tmp_path, "init", "--bare", str(remote))
    _git(repository, "remote", "add", "origin", str(remote))
    commit = _git(repository, "rev-parse", "HEAD")

    result = create_release_tags(
        repository,
        ("python",),
        commit=commit,
        publication_checker=lambda _requirement: True,
    )

    assert result.created == ("python-v1.2.3",)
    assert _git(remote, "rev-list", "-n", "1", "refs/tags/python-v1.2.3") == commit

    (repository / "README.md").write_text("unrelated change\n", encoding="utf-8")
    _git(repository, "add", "README.md")
    _git(
        repository,
        "-c",
        "user.email=release-test@example.com",
        "-c",
        "user.name=Release Test",
        "commit",
        "-m",
        "unrelated",
    )
    newer_commit = _git(repository, "rev-parse", "HEAD")

    retry = create_release_tags(
        repository,
        ("python",),
        commit=newer_commit,
        publication_checker=lambda _requirement: True,
    )

    assert retry.created == ()
    assert retry.existing == ("python-v1.2.3",)


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


def test_create_standards_tag_requires_both_registry_projects(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if argv[:3] == ("git", "rev-parse", "--verify"):
            return ProcessResult(0)
        raise ProcessFailureError(argv, 2)

    with pytest.raises(ValueError, match=r"sarj-standards@1\.2\.3"):
        create_release_tags(
            tmp_path,
            ("standards",),
            commit="publish-sha",
            runner=runner,
            publication_checker=lambda requirement: requirement.name == "code-standards",
        )


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
            resolved = "different-commit" if argv[-1] == "different-commit^{commit}" else "published-commit"
            return ProcessResult(0, f"{resolved}\n")
        if argv[-1] == "refs/tags/python-v1.2.3":
            return ProcessResult(0)
        if argv[-1] == "refs/tags/python-v1.2.3^{}":
            return ProcessResult(
                0,
                "tag-object\trefs/tags/python-v1.2.3\ndifferent-commit\trefs/tags/python-v1.2.3^{}\n",
            )
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            return ProcessResult(0)
        if argv[:3] == ("git", "diff", "--quiet"):
            raise ProcessFailureError(argv, 1)
        raise AssertionError(argv)

    with pytest.raises(ValueError, match="not publishing commit published-commit"):
        create_release_tags(
            tmp_path,
            ("python",),
            commit="publish-sha",
            runner=runner,
            publication_checker=lambda _requirement: True,
        )


def test_create_release_tags_accepts_unchanged_target_tagged_on_older_commit(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if argv[:3] == ("git", "rev-parse", "--verify"):
            resolved = "older-commit" if argv[-1] == "older-commit^{commit}" else "published-commit"
            return ProcessResult(0, f"{resolved}\n")
        if argv[-1] == "refs/tags/python-v1.2.3":
            return ProcessResult(0)
        if argv[-1] == "refs/tags/python-v1.2.3^{}":
            return ProcessResult(
                0,
                "tag-object\trefs/tags/python-v1.2.3\nolder-commit\trefs/tags/python-v1.2.3^{}\n",
            )
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            return ProcessResult(0)
        if argv == (
            "git",
            "diff",
            "--quiet",
            "older-commit",
            "published-commit",
            "--",
            "packages/python/pyproject.toml",
            "packages/python/LICENSE",
            "packages/python/src/",
        ):
            return ProcessResult(0)
        raise AssertionError(argv)

    result = create_release_tags(
        tmp_path,
        ("python",),
        commit="publish-sha",
        runner=runner,
        publication_checker=lambda _requirement: True,
    )

    assert result.created == ()
    assert result.existing == ("python-v1.2.3",)


def test_create_release_tags_rejects_non_ancestor_with_unchanged_target_tree(tmp_path: Path) -> None:
    _write_release_manifests(tmp_path)

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if argv[:3] == ("git", "rev-parse", "--verify"):
            resolved = "future-commit" if argv[-1] == "future-commit^{commit}" else "published-commit"
            return ProcessResult(0, f"{resolved}\n")
        if argv[-1] == "refs/tags/python-v1.2.3":
            return ProcessResult(0)
        if argv[-1] == "refs/tags/python-v1.2.3^{}":
            return ProcessResult(0, "future-commit\trefs/tags/python-v1.2.3^{}\n")
        if argv[:3] == ("git", "merge-base", "--is-ancestor"):
            raise ProcessFailureError(argv, 1)
        if argv[:3] == ("git", "diff", "--quiet"):
            msg = "non-ancestor tags must be rejected before tree comparison"
            raise AssertionError(msg)
        raise AssertionError(argv)

    with pytest.raises(ValueError, match="not an ancestor of publishing commit"):
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
