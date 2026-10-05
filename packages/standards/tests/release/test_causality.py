from __future__ import annotations

import subprocess
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

    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        capture_output: bool = False,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessResult:
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

    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        capture_output: bool = False,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessResult:
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


@pytest.mark.parametrize(
    "changed_path",
    ["packages/typescript/src/index.ts", "packages/typescript/types/astro.d.ts"],
    ids=("runtime-source", "exported-declaration"),
)
def test_json_package_failure_names_its_exact_version_field(tmp_path: Path, changed_path: str) -> None:
    _write_manifest(tmp_path, "packages/typescript/package.json", "15.17.18", json=True)

    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        capture_output: bool = False,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessResult:
        if "--name-only" in argv:
            return ProcessResult(0, f"{changed_path}\0")
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
        f"publishable files changed: {changed_path}"
    )


@pytest.mark.parametrize(
    "changed_path",
    ["packages/typescript/scripts/copy-native-assets.mjs", "packages/typescript/tsup.config.ts"],
    ids=("asset-copy-script", "bundle-configuration"),
)
def test_build_input_only_change_requires_a_package_version_bump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_path: str
) -> None:
    local_environment = subprocess.run(
        ("git", "rev-parse", "--local-env-vars"), check=True, capture_output=True, text=True
    ).stdout.splitlines()
    for key in local_environment:
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)

    def git(*args: str) -> str:
        return subprocess.run(("git", *args), cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()

    git("init")
    git("config", "user.email", "release-test@example.com")
    git("config", "user.name", "Release Test")
    package = tmp_path / "packages/typescript/package.json"
    package.parent.mkdir(parents=True)
    package.write_text('{\n  "version": "17.0.0"\n}\n', encoding="utf-8")
    build_input = tmp_path / changed_path
    build_input.parent.mkdir(parents=True, exist_ok=True)
    build_input.write_text('export const asset = "original";\n', encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "published build input")
    before = git("rev-parse", "HEAD")
    build_input.write_text('export const asset = "changed";\n', encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "change published build input")
    after = git("rev-parse", "HEAD")

    report = check_release_causality(
        tmp_path,
        before=before,
        after=after,
        tag_checker=lambda *_args, **_kwargs: False,
        publication_checker=lambda _requirement: True,
    )

    assert not report.ok
    assert report.changed_targets == ("typescript",)
    assert report.violations[0].render() == (
        'typescript: bump top-level "version" in packages/typescript/package.json; '
        f"publishable files changed: {changed_path}"
    )

    package.write_text('{\n  "version": "17.0.1"\n}\n', encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "bump package for changed build input")
    report = check_release_causality(
        tmp_path,
        before=before,
        after=git("rev-parse", "HEAD"),
        tag_checker=lambda *_args, **_kwargs: True,
        publication_checker=lambda _requirement: True,
    )

    assert report.ok
    assert report.changed_targets == report.bumped_targets == ("typescript",)


def test_compatibility_source_is_owned_by_the_atomic_standards_release(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "packages/standards/pyproject.toml", "7.15.14")

    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        capture_output: bool = False,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessResult:
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

    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        capture_output: bool = False,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessResult:
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
    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        capture_output: bool = False,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessResult:
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
    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        capture_output: bool = False,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessResult:
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
    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        capture_output: bool = False,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessResult:
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
    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        capture_output: bool = False,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessResult:
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

    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        capture_output: bool = False,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessResult:
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

    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        capture_output: bool = False,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessResult:
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
    def runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
        capture_output: bool = False,  # ruff: ignore[unused-function-argument] -- ProcessRunner fixes this keyword.
    ) -> ProcessResult:
        if "--name-only" in argv:
            return ProcessResult(
                0,
                "packages/python/tests/test_api.py\0packages/python/uv.lock\0packages/python/README.md\0",
            )
        return ProcessResult(0, "")

    report = check_release_causality(tmp_path, before="base", after="head", runner=runner)

    assert report.ok
    assert not report.changed_targets
