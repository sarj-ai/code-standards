# /// script
# requires-python = ">=3.14"
# dependencies = ["typer==0.27.3", "pydantic==2.14.1"]
# ///

from __future__ import annotations

from enum import StrEnum
import hashlib
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- inspect only the trusted checkout's Git objects.
import sys
import tomllib
from typing import Annotated, ClassVar, Final, Literal

from pydantic import ConfigDict, JsonValue, RootModel
import typer


MAINTENANCE_REF = "refs/heads/maintenance/standards-8.101"
LEGACY_COMMIT = "14270016f74006a1c8fe2765d5a4258c6b4d4cb8"
LEGACY_VERSION = "8.101.1"
# Reviewed candidate bytes; publication still requires successful native qualification
# and exact-source release gates. Pinning this digest alone does not qualify a release.
APPROVED_ADAPTER_SHA256 = "b949ddf7fb6aadbf9e5fd4520b67a322b114a0b54a0af2b32c21d1a2644d882c"
# The paired scoped-scan backport is required from 8.101.5 onward.
REACT_SCOPE_TESTS = "packages/standards/tests/test_react_doctor_scope.py"
APPROVED_SCOPED_ADAPTER_SHA256 = "34a44e73a15dc8b3a50a7d8662cbe6471d7fbf2303d07e32e17338ce109a5f7c"
APPROVED_SCOPED_TESTS_SHA256 = "0e62a69a71c7257de526619ef6cfda4cf824cfa5825edc961f7a28b8e014136b"
APPROVED_LOCK_SHA256 = "64dfbdabf646cef05c003036c6849c5922d67865e27e94012a3e37a670777e28"
# Historical 8.101.2/3 retain their exact lock; later patches must carry both reviewed dependency fixes.
APPROVED_PATCHED_LOCK_SHA256 = "a7df5c1149f9b655cd587b49cc3e2bdc1c484e7bd5092aa43c6d6b8903c84698"
APPROVED_GITLEAKS_SHA256 = "1fe4ec30d50367745d11b1e0fbb7bf384c1fc12abb0c1f6aa28a4c115b63158b"
SECURITY_PROJECTIONS = frozenset({".gitleaks.toml"})
DOCS_SECURITY_PROJECTIONS: Final[dict[str, str]] = {
    "apps/docs/package.json": "f9115736acc3d86f75bbe99c9881d04178a697a2e7c2bce402126825dde4cd06",
    "apps/docs/package-lock.json": "6f884f90258886a3fc83717c99dad498bd056e4ed1f9ec92c19c9e098995fd0c",
    ".github/deploy/package.json": "ec9e370c0cea9794344e559177caabd93cc8b87bc626bc0b3adc24543927574e",
    ".github/deploy/package-lock.json": "d32b91687d54fa3003c594f5fc3b44204937d0507a740c4b7b3f2bf6de787924",
}
PACKAGE = "packages/standards"
CLI_REFERENCE = f"{PACKAGE}/src/sarj_standards/configs/cli-reference.v1.json"
DOC_EXAMPLES = "apps/docs/src/generated/formatted-code.v1.json"
TOOLING_PATHS = frozenset(
    {
        ".github/scripts/release_lane.py",
        ".github/scripts/release-github-release.sh",
        ".github/scripts/release-require-checks.sh",
        ".github/workflows/release.yml",
        ".github/workflows/release-tags.yml",
        ".github/workflows/ci.yml",
        ".github/workflows/repo-ci.yml",
        ".github/workflows/private-refs.yml",
        f"{PACKAGE}/tests/release/test_release_lane.py",
        f"{PACKAGE}/tests/release/test_workflow.py",
        f"{PACKAGE}/tests/test_supply_chain.py",
    }
)
VERSION_PROJECTIONS = (
    f"{PACKAGE}/pyproject.toml",
    "packages/standards-compat/pyproject.toml",
    f"{PACKAGE}/uv.lock",
    ".sarj-standards.toml",
    CLI_REFERENCE,
)
BACKPORT_PATHS = frozenset(
    {
        *VERSION_PROJECTIONS,
        DOC_EXAMPLES,
        f"{PACKAGE}/src/sarj_standards/libs/linting/external.py",
        f"{PACKAGE}/tests/test_external_diagnostics.py",
        f"{PACKAGE}/tests/test_python_type_scope.py",
        REACT_SCOPE_TESTS,
    }
)
# Exact whole-file projection of #1637 onto the reviewed 8.101.3 source; no other generator edits are approved.
COMMIT_POLICY_BACKPORT_SHA256 = {
    f"{PACKAGE}/src/sarj_standards/libs/adoption/scaffold.py": (
        "8a656b177839655c9bc34c8dc7ed751e559cdc342f44fd608d38bf6b7efd9c3d"
    ),
    f"{PACKAGE}/tests/test_adoption.py": "20d9cee4883b50e9d6357548f10684084e69e265f704ab6d122963125efa483c",
    ".github/workflows/commit-policy.yml": "21a5f6293e41a052e032305d286b641e61aac2f668470bc1dee01ee2098761fb",
}
# Action delivery is independent of the retained 6.11 runtime policy.
REPO_STANDARDS_ACTION_FIRST_PATCH: int | None = 6
REPO_STANDARDS_ACTION_PROJECTIONS: Final[dict[str, str]] = {
    "packages/standards/src/sarj_standards/libs/adoption/manifest.py": "1a413118794fa06d59cd98e098f2afbf005c16b5020d7df8781133e451dac723",
    "packages/standards/tests/test_repo_standards_pins.py": "553545d6335022dc0ddae6529311a3e37667a0342da74c311671042162baa88e",
    ".github/workflows/ci.yml": "dd39d386dd144709848675ba4d33964b95d9d1dc5c8db15679034bb62f300628",
    ".github/workflows/commit-policy.yml": "4de0749743f162c9bc6ac08492c8bc458503157510df7927eb30d1319f1c0446",
}
RELEASE_TARGETS = frozenset({"typescript", "bootstrap", "contracts", "python", "sql", "iac", "standards", "tsconfig"})


class Lane(StrEnum):
    MAIN = "main"
    MAINTENANCE = "standards-maintenance"


class ReleaseLaneError(ValueError):
    """The checkout does not satisfy its named publication lane."""


class _Document(RootModel[dict[str, JsonValue]]):
    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True)


class _Targets(RootModel[dict[str, Literal["true", "false"]]]):
    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True)


def _git(root: Path, *arguments: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        msg = "Git must be installed before release lane validation"
        raise ReleaseLaneError(msg)
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed Git executable; validated revision/path arguments, no shell.
        (executable, "-C", str(root), *arguments), check=True, capture_output=True, timeout=30
    ).stdout


def _at(root: Path, commit: str, path: str) -> bytes:
    return _git(root, "show", f"{commit}:{path}")


def validate_lane(root: Path, *, source_ref: str, commit: str, detected_targets: str | None = None) -> Lane:
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None or _git(root, "rev-parse", "HEAD").decode().strip() != commit:
        msg = "release lane requires the exact checked-out full commit SHA"
        raise ReleaseLaneError(msg)
    if source_ref == "refs/heads/main":
        return Lane.MAIN
    if source_ref != MAINTENANCE_REF:
        msg = f"publication ref is not allowed: {source_ref}"
        raise ReleaseLaneError(msg)
    _validate_maintenance(root, commit)
    if detected_targets is not None:
        targets = _Targets.model_validate_json(detected_targets)
        if targets.root.keys() != RELEASE_TARGETS:
            msg = "maintenance requires the complete known release-target inventory"
            raise ReleaseLaneError(msg)
        unexpected = sorted(name for name, value in targets.root.items() if value == "true" and name != "standards")
        if unexpected:
            msg = f"maintenance cannot publish sibling targets: {', '.join(unexpected)}"
            raise ReleaseLaneError(msg)
    return Lane.MAINTENANCE


def _validate_maintenance(root: Path, commit: str) -> None:
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        msg = "maintenance publication requires a clean working tree"
        raise ReleaseLaneError(msg)
    _git(root, "merge-base", "--is-ancestor", LEGACY_COMMIT, commit)
    changed = frozenset(
        path.decode() for path in _git(root, "diff", "--name-only", "-z", LEGACY_COMMIT, commit).split(b"\0") if path
    )
    unexpected = (
        changed
        - BACKPORT_PATHS
        - TOOLING_PATHS
        - SECURITY_PROJECTIONS
        - COMMIT_POLICY_BACKPORT_SHA256.keys()
        - DOCS_SECURITY_PROJECTIONS.keys()
        - REPO_STANDARDS_ACTION_PROJECTIONS.keys()
    )
    if unexpected:
        msg = f"maintenance changes legacy policy or an unapproved path: {', '.join(sorted(unexpected))}"
        raise ReleaseLaneError(msg)
    version = _maintenance_version(root, commit)
    action_backport = _validate_repo_standards_actions(root, commit, version, changed)
    for path in VERSION_PROJECTIONS:
        _validate_projection(root, commit, path, version)
    _validate_docs(root, commit)
    _validate_docs_dependencies(root, commit, version)
    _validate_adapter(root, commit, version)
    _validate_gitleaks(root, commit)
    _validate_commit_policy_backport(root, commit, changed, action_backport=action_backport)


def _validate_commit_policy_backport(
    root: Path, commit: str, changed: frozenset[str], *, action_backport: bool
) -> None:
    if not changed.intersection(COMMIT_POLICY_BACKPORT_SHA256):
        return
    if not changed.issuperset(COMMIT_POLICY_BACKPORT_SHA256):
        msg = "maintenance commit-policy backport requires all three approved files"
        raise ReleaseLaneError(msg)
    for path, expected in COMMIT_POLICY_BACKPORT_SHA256.items():
        reviewed = REPO_STANDARDS_ACTION_PROJECTIONS.get(path, expected) if action_backport else expected
        if hashlib.sha256(_at(root, commit, path)).hexdigest() != reviewed:
            msg = f"maintenance commit-policy backport must match the exact approved bytes in {path}"
            raise ReleaseLaneError(msg)


def _validate_repo_standards_actions(root: Path, commit: str, version: str, changed: frozenset[str]) -> bool:
    # Older candidates may inherit the complete reviewed action defaults after rebasing.
    default_changes = (
        changed.intersection(REPO_STANDARDS_ACTION_PROJECTIONS) - TOOLING_PATHS - COMMIT_POLICY_BACKPORT_SHA256.keys()
    )
    first_patch = REPO_STANDARDS_ACTION_FIRST_PATCH
    action_backport = first_patch is not None and (
        int(version.rpartition(".")[2]) >= first_patch or bool(default_changes)
    )
    if not action_backport:
        if default_changes:
            msg = f"maintenance changes legacy policy or an unapproved path: {', '.join(sorted(default_changes))}"
            raise ReleaseLaneError(msg)
        return False
    for path, expected in REPO_STANDARDS_ACTION_PROJECTIONS.items():
        if hashlib.sha256(_at(root, commit, path)).hexdigest() != expected:
            msg = f"maintenance RepoStandards actions must match the exact approved bytes in {path}"
            raise ReleaseLaneError(msg)
    return True


def _maintenance_version(root: Path, commit: str) -> str:
    project = _Document.model_validate(tomllib.loads(_at(root, commit, f"{PACKAGE}/pyproject.toml").decode())).root
    table = project.get("project")
    version = table.get("version") if isinstance(table, dict) else None
    if not isinstance(version, str) or re.fullmatch(r"8\.101\.(?:[2-9]|[1-9][0-9]+)", version) is None:
        msg = "maintenance publication requires an exact 8.101.x version"
        raise ReleaseLaneError(msg)
    return version


def _validate_projection(root: Path, commit: str, path: str, version: str) -> None:
    original = _at(root, LEGACY_COMMIT, path)
    current = _at(root, commit, path)
    if not _matches_projection(original, current, path, version):
        msg = f"maintenance may change only the legacy version projection and reviewed security projection in {path}"
        raise ReleaseLaneError(msg)


def _matches_projection(original: bytes, current: bytes, path: str, version: str) -> bool:
    if path != f"{PACKAGE}/uv.lock":
        return current == original.replace(LEGACY_VERSION.encode(), version.encode())
    normalized = current.replace(version.encode(), LEGACY_VERSION.encode())
    expected = APPROVED_LOCK_SHA256 if version in {"8.101.2", "8.101.3"} else APPROVED_PATCHED_LOCK_SHA256
    return hashlib.sha256(normalized).hexdigest() == expected and current == normalized.replace(
        LEGACY_VERSION.encode(), version.encode()
    )


def _validate_docs(root: Path, commit: str) -> None:
    expected = _Document.model_validate_json(_at(root, LEGACY_COMMIT, DOC_EXAMPLES))
    expected.root["cliSha256"] = hashlib.sha256(_at(root, commit, CLI_REFERENCE)).hexdigest()
    if _Document.model_validate_json(_at(root, commit, DOC_EXAMPLES)) != expected:
        msg = "maintenance documentation must retain the legacy catalog, snippets and formatters"
        raise ReleaseLaneError(msg)


def _validate_docs_dependencies(root: Path, commit: str, version: str) -> None:
    for path, reviewed_digest in DOCS_SECURITY_PROJECTIONS.items():
        expected = (
            hashlib.sha256(_at(root, LEGACY_COMMIT, path)).hexdigest()
            if version in {"8.101.2", "8.101.3"}
            else reviewed_digest
        )
        if hashlib.sha256(_at(root, commit, path)).hexdigest() != expected:
            msg = f"maintenance docs dependencies must match the exact reviewed version-specific bytes in {path}"
            raise ReleaseLaneError(msg)


def _validate_adapter(root: Path, commit: str, version: str) -> None:
    legacy = version in {"8.101.2", "8.101.3", "8.101.4"}
    adapter = _at(root, commit, f"{PACKAGE}/src/sarj_standards/libs/linting/external.py")
    expected_adapter = APPROVED_ADAPTER_SHA256 if legacy else APPROVED_SCOPED_ADAPTER_SHA256
    if hashlib.sha256(adapter).hexdigest() != expected_adapter:
        msg = "maintenance adapter bytes do not match the independently reviewed backport"
        raise ReleaseLaneError(msg)
    expected_tests = (
        hashlib.sha256(_at(root, LEGACY_COMMIT, REACT_SCOPE_TESTS)).hexdigest()
        if legacy
        else APPROVED_SCOPED_TESTS_SHA256
    )
    if hashlib.sha256(_at(root, commit, REACT_SCOPE_TESTS)).hexdigest() != expected_tests:
        msg = "maintenance React Doctor scope tests do not match the reviewed backport"
        raise ReleaseLaneError(msg)


def _validate_gitleaks(root: Path, commit: str) -> None:
    if hashlib.sha256(_at(root, commit, ".gitleaks.toml")).hexdigest() != APPROVED_GITLEAKS_SHA256:
        msg = "maintenance scanner configuration must match the exact reviewed public-digest projection"
        raise ReleaseLaneError(msg)


def main(argv: list[str] | None = None) -> int:
    app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)

    @app.command()
    def validate(
        root: Annotated[Path, typer.Option("--root")],
        source_ref: Annotated[str, typer.Option("--ref")],
        commit: Annotated[str, typer.Option("--commit")],
        github_output: Annotated[Path | None, typer.Option("--github-output")] = None,
        detected_targets: Annotated[str | None, typer.Option("--detected-targets")] = None,
    ) -> None:
        lane = validate_lane(root, source_ref=source_ref, commit=commit, detected_targets=detected_targets)
        if github_output is not None:
            with github_output.open("a", encoding="utf-8") as output:
                output.write(f"lane={lane}\n")
        sys.stdout.write(f"Validated {lane} publication at {commit}\n")

    try:
        app(args=argv, prog_name="release-lane")
    except SystemExit as exc:
        if exc.code != 0:
            raise
    except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
