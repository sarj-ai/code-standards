from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.release.causality import check_release_causality
from sarj_standards.libs.release.process import ProcessFailureError, ProcessResult
from sarj_standards.libs.release.registry import RegistryRequirement


if TYPE_CHECKING:
    from pathlib import Path


def _write_manifest(tmp_path: Path, relative: str, version: str, *, json: bool = False) -> None:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    contents = f'{{"version":"{version}"}}\n' if json else f'[project]\nversion = "{version}"\n'
    path.write_text(contents, encoding="utf-8")


def test_publishable_source_change_without_version_bump_fails(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "packages/python/pyproject.toml", "0.49.0")

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(0, "packages/python/src/sarj_python_lint/api.py\0")
        return ProcessResult(0, "")

    report = check_release_causality(
        tmp_path,
        before="base",
        after="head",
        runner=runner,
        tag_checker=lambda *_args, **_kwargs: False,
        publication_checker=lambda _requirement: True,
    )

    assert not report.ok
    assert report.changed_targets == ("python",)
    assert report.violations[0].target == "python"
    assert report.violations[0].render() == (
        "python: bump [project].version in packages/python/pyproject.toml; "
        "publishable files changed: packages/python/src/sarj_python_lint/api.py"
    )


def test_bootstrap_source_is_owned_by_the_bootstrap_release(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "packages/bootstrap/pyproject.toml", "0.8.0")

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(0, "packages/bootstrap/src/sarj_standards_bootstrap/__main__.py\0")
        return ProcessResult(0, "")

    report = check_release_causality(
        tmp_path,
        before="base",
        after="head",
        runner=runner,
        tag_checker=lambda *_args, **_kwargs: False,
        publication_checker=lambda _requirement: True,
    )

    assert not report.ok
    assert report.changed_targets == ("bootstrap",)
    assert report.violations[0].manifest.as_posix() == "packages/bootstrap/pyproject.toml"


def test_json_package_failure_names_its_exact_version_field(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "packages/typescript/package.json", "15.17.18", json=True)

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(0, "packages/typescript/src/index.ts\0")
        return ProcessResult(0, "")

    report = check_release_causality(
        tmp_path,
        before="base",
        after="head",
        runner=runner,
        tag_checker=lambda *_args, **_kwargs: False,
        publication_checker=lambda _requirement: True,
    )

    assert report.violations[0].render() == (
        'typescript: bump top-level "version" in packages/typescript/package.json; '
        "publishable files changed: packages/typescript/src/index.ts"
    )


def test_compatibility_source_is_owned_by_the_atomic_standards_release(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "packages/standards/pyproject.toml", "7.15.14")

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(0, "packages/standards-compat/src/sarj_standards_compat/__init__.py\0")
        return ProcessResult(0, "")

    report = check_release_causality(
        tmp_path,
        before="base",
        after="head",
        runner=runner,
        tag_checker=lambda *_args, **_kwargs: False,
        publication_checker=lambda _requirement: True,
    )

    assert not report.ok
    assert report.changed_targets == ("standards",)


def test_unpublished_current_version_can_be_repaired_without_another_bump(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "packages/standards/pyproject.toml", "7.15.14")

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(0, "packages/standards/src/sarj_standards/release.py\0")
        return ProcessResult(0, "")

    checked: list[RegistryRequirement] = []

    def publication_checker(requirement: RegistryRequirement) -> bool:
        checked.append(requirement)
        return False

    report = check_release_causality(
        tmp_path,
        before="base",
        after="head",
        runner=runner,
        tag_checker=lambda *_args, **_kwargs: False,
        publication_checker=publication_checker,
    )

    assert report.ok
    assert checked == [
        RegistryRequirement("pypi", "code-standards", "7.15.14"),
        RegistryRequirement("pypi", "sarj-standards", "7.15.14"),
    ]


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
        if argv[:2] == ("git", "show"):
            return ProcessResult(0, 'version = "0.49.0"\n')
        return ProcessResult(0, "")

    report = check_release_causality(
        tmp_path,
        before="base",
        after="head",
        runner=runner,
        tag_checker=lambda *_args, **_kwargs: True,
    )

    assert report.ok
    assert report.bumped_targets == ("python",)


def test_version_bump_cannot_supersede_an_unverified_prior_release(tmp_path: Path) -> None:
    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(0, "packages/python/pyproject.toml\0")
        if argv[:2] == ("git", "show"):
            return ProcessResult(0, 'version = "0.49.0"\n')
        if argv[-1] == "packages/python/pyproject.toml":
            return ProcessResult(0, '+version = "0.50.0"\n')
        return ProcessResult(0, "")

    report = check_release_causality(
        tmp_path,
        before="base",
        after="head",
        runner=runner,
        tag_checker=lambda *_args, **_kwargs: False,
        publication_checker=lambda _requirement: True,
    )

    assert not report.ok
    assert report.violations[-1].render() == "python: cannot supersede unverified prior release python-v0.49.0"


def test_version_bump_can_supersede_a_prior_release_absent_from_the_registry(tmp_path: Path) -> None:
    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(0, "packages/python/pyproject.toml\0")
        if argv[:2] == ("git", "show"):
            return ProcessResult(0, 'version = "0.49.0"\n')
        if argv[-1] == "packages/python/pyproject.toml":
            return ProcessResult(0, '+version = "0.50.0"\n')
        return ProcessResult(0, "")

    checked: list[RegistryRequirement] = []

    def publication_checker(requirement: RegistryRequirement) -> bool:
        checked.append(requirement)
        return False

    report = check_release_causality(
        tmp_path,
        before="base",
        after="head",
        runner=runner,
        tag_checker=lambda *_args, **_kwargs: False,
        publication_checker=publication_checker,
    )

    assert report.ok
    assert checked == [RegistryRequirement("pypi", "sarj-python-lint", "0.49.0")]


def test_version_bump_fails_closed_when_prior_registry_lookup_fails(tmp_path: Path) -> None:
    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(0, "packages/python/pyproject.toml\0")
        if argv[:2] == ("git", "show"):
            return ProcessResult(0, 'version = "0.49.0"\n')
        if argv[-1] == "packages/python/pyproject.toml":
            return ProcessResult(0, '+version = "0.50.0"\n')
        return ProcessResult(0, "")

    def publication_checker(_requirement: RegistryRequirement) -> bool:
        message = "registry unavailable"
        raise OSError(message)

    with pytest.raises(OSError, match="registry unavailable"):
        check_release_causality(
            tmp_path,
            before="base",
            after="head",
            runner=runner,
            tag_checker=lambda *_args, **_kwargs: False,
            publication_checker=publication_checker,
        )


@pytest.mark.parametrize("prior_tree", ["missing-manifest", "existing-manifest", "invalid-revision"])
def test_initial_contracts_release_requires_proven_absence_of_a_prior_manifest(tmp_path: Path, prior_tree: str) -> None:
    manifest = "packages/contracts/pyproject.toml"

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if argv[:2] == ("git", "show"):
            raise ProcessFailureError(argv, 128)
        if argv[:2] == ("git", "ls-tree"):
            if prior_tree == "invalid-revision":
                raise ProcessFailureError(argv, 128)
            return ProcessResult(0, f"{manifest}\n" if prior_tree == "existing-manifest" else "")
        if "--name-only" in argv:
            return ProcessResult(0, f"{manifest}\0packages/contracts/src/sarj_rule_contracts/contracts.py\0")
        return ProcessResult(0, '+version = "1.0.0"\n' if argv[-1] == manifest else "")

    def unexpected_publication(_requirement: RegistryRequirement) -> bool:
        pytest.fail("a new manifest has no previous release to look up")

    if prior_tree == "missing-manifest":
        report = check_release_causality(
            tmp_path, before="base", after="head", runner=runner, publication_checker=unexpected_publication
        )
        assert report.ok
        assert report.changed_targets == ("contracts",)
        assert report.bumped_targets == ("contracts",)
    else:
        with pytest.raises(ProcessFailureError):
            check_release_causality(
                tmp_path, before="base", after="head", runner=runner, publication_checker=unexpected_publication
            )


def test_non_publishable_push_is_a_clean_release_recovery_barrier(tmp_path: Path) -> None:
    checked_tags: list[str] = []

    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(0, ".github/workflows/release.yml\0")
        return ProcessResult(0, "")

    def tag_checker(*_args: object, **_kwargs: object) -> bool:
        checked_tags.append("unexpected")
        return False

    report = check_release_causality(
        tmp_path,
        before="blocked-release",
        after="recovery-barrier",
        runner=runner,
        tag_checker=tag_checker,
    )

    assert report.ok
    assert report.changed_targets == ()
    assert report.bumped_targets == ()
    assert checked_tags == []


def test_tests_locks_and_generated_readmes_do_not_force_noop_releases(tmp_path: Path) -> None:
    def runner(argv: tuple[str, ...], *, cwd: Path, capture_output: bool = False) -> ProcessResult:
        _ = cwd, capture_output
        if "--name-only" in argv:
            return ProcessResult(
                0,
                "packages/python/tests/test_api.py\0packages/python/uv.lock\0packages/python/README.md\0",
            )
        return ProcessResult(0, "")

    report = check_release_causality(tmp_path, before="base", after="head", runner=runner)

    assert report.ok
    assert not report.changed_targets
