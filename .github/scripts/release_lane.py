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
from typing import Annotated, ClassVar, Literal

from pydantic import ConfigDict, JsonValue, RootModel
import typer


MAINTENANCE_REF = "refs/heads/maintenance/standards-8.101"
LEGACY_COMMIT = "14270016f74006a1c8fe2765d5a4258c6b4d4cb8"
LEGACY_VERSION = "8.101.1"
# Reviewed candidate bytes; publication still requires successful native qualification
# and exact-source release gates. Pinning this digest alone does not qualify a release.
APPROVED_ADAPTER_SHA256 = "b949ddf7fb6aadbf9e5fd4520b67a322b114a0b54a0af2b32c21d1a2644d882c"
APPROVED_LOCK_SHA256 = "64dfbdabf646cef05c003036c6849c5922d67865e27e94012a3e37a670777e28"
APPROVED_GITLEAKS_SHA256 = "1fe4ec30d50367745d11b1e0fbb7bf384c1fc12abb0c1f6aa28a4c115b63158b"
SECURITY_PROJECTIONS = frozenset({".gitleaks.toml"})
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
    }
)
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
    unexpected = changed - BACKPORT_PATHS - TOOLING_PATHS - SECURITY_PROJECTIONS
    if unexpected:
        msg = f"maintenance changes legacy policy or an unapproved path: {', '.join(sorted(unexpected))}"
        raise ReleaseLaneError(msg)
    version = _maintenance_version(root, commit)
    for path in VERSION_PROJECTIONS:
        _validate_projection(root, commit, path, version)
    _validate_docs(root, commit)
    _validate_adapter(root, commit)
    _validate_gitleaks(root, commit)


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
    return hashlib.sha256(normalized).hexdigest() == APPROVED_LOCK_SHA256 and current == normalized.replace(
        LEGACY_VERSION.encode(), version.encode()
    )


def _validate_docs(root: Path, commit: str) -> None:
    expected = _Document.model_validate_json(_at(root, LEGACY_COMMIT, DOC_EXAMPLES))
    expected.root["cliSha256"] = hashlib.sha256(_at(root, commit, CLI_REFERENCE)).hexdigest()
    if _Document.model_validate_json(_at(root, commit, DOC_EXAMPLES)) != expected:
        msg = "maintenance documentation must retain the legacy catalog, snippets and formatters"
        raise ReleaseLaneError(msg)


def _validate_adapter(root: Path, commit: str) -> None:
    adapter = _at(root, commit, f"{PACKAGE}/src/sarj_standards/libs/linting/external.py")
    if hashlib.sha256(adapter).hexdigest() != APPROVED_ADAPTER_SHA256:
        msg = "maintenance adapter bytes do not match the independently reviewed backport"
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
