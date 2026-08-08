"""Authoritative registry proofs for coherent releases and recovery tags."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import timedelta
import json
from pathlib import Path
import re
import sys
import time
import tomllib
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, Protocol
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from sarj_lint_configs.libs.release._values import is_object_dict, is_object_list, string_object_dict
from sarj_lint_configs.libs.release.tags import RELEASE_TARGETS, read_manifest_version


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


RegistryKind = Literal["npm", "pypi"]


@dataclass(frozen=True, slots=True, order=True)
class RegistryRequirement:
    """One exact package version that must exist before dependent publication."""

    registry: RegistryKind
    name: str
    version: str


class PublicationChecker(Protocol):
    """Prove that one exact registry package version is publicly available."""

    def __call__(self, requirement: RegistryRequirement, /) -> bool: ...


class _Args(argparse.Namespace):
    root: Path = Path()
    attempts: int = 6
    delay: timedelta = timedelta(seconds=10)


_TARGET_PACKAGES: Final[Mapping[str, tuple[RegistryKind, str]]] = MappingProxyType(
    {
        "typescript": ("npm", "@sarj/eslint-plugin"),
        "python": ("pypi", "sarj-python-lint"),
        "sql": ("pypi", "sarj-sql-lint"),
        "iac": ("pypi", "sarj-iac-lint"),
        "lint-configs": ("pypi", "sarj-lint-configs"),
        "tsconfig": ("npm", "@sarj/tsconfig"),
    }
)
_EXACT_DEPENDENCY = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^;\s]+)$")
_HTTP_OK = 200
_HTTP_NOT_FOUND = 404


def target_requirement(root: Path, target_name: str) -> RegistryRequirement:
    """Derive one registry identity from its authoritative package manifest."""
    target = RELEASE_TARGETS.get(target_name)
    package = _TARGET_PACKAGES.get(target_name)
    if target is None or package is None:
        msg = f"unsupported release target: {target_name}"
        raise ValueError(msg)
    registry, name = package
    version = read_manifest_version(root.resolve() / target.manifest, target.format)
    return RegistryRequirement(registry, name, version)


def publication_exists(requirement: RegistryRequirement) -> bool:
    """Query the authoritative public registry for one exact version."""
    if requirement.registry == "pypi":
        url = f"https://pypi.org/pypi/{quote(requirement.name, safe='')}/{quote(requirement.version, safe='')}/json"
    else:
        url = f"https://registry.npmjs.org/{quote(requirement.name, safe='')}/{quote(requirement.version, safe='')}"
    request = Request(  # ruff: ignore[suspicious-url-open-usage] -- URL is constructed only from fixed HTTPS registry origins.
        url, headers={"Accept": "application/json"}
    )
    try:
        with urlopen(request, timeout=15) as response:  # ruff: ignore[suspicious-url-open-usage]  # pyright: ignore[reportAny] -- fixed registry origins
            return response.status == _HTTP_OK  # pyright: ignore[reportAny]
    except HTTPError as exc:
        if exc.code == _HTTP_NOT_FOUND:
            return False
        raise


def require_publication(
    requirement: RegistryRequirement,
    *,
    checker: PublicationChecker = publication_exists,
) -> None:
    """Reject release continuation until an exact registry version is visible."""
    if checker(requirement):
        return
    msg = f"{requirement.registry} publication is unavailable: {requirement.name}@{requirement.version}"
    raise ValueError(msg)


def lint_config_requirements(root: Path) -> tuple[RegistryRequirement, ...]:
    """Read every exact sibling version the compatibility bundle publishes."""
    resolved = root.resolve()
    pyproject = resolved / "packages/lint-configs/pyproject.toml"
    try:
        with pyproject.open("rb") as stream:
            parsed: object = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        msg = f"could not read compatibility-bundle manifest {pyproject}: {exc}"
        raise ValueError(msg) from exc
    project = string_object_dict(parsed, label="lint-configs manifest")
    project_table = project.get("project")
    if not is_object_dict(project_table):
        msg = f"{pyproject} has no project table"
        raise ValueError(msg)
    dependencies = string_object_dict(project_table, label="lint-configs project").get("dependencies")
    if not is_object_list(dependencies):
        msg = f"{pyproject} has no dependency list"
        raise ValueError(msg)
    requirements: list[RegistryRequirement] = []
    for dependency in dependencies:
        if not isinstance(dependency, str) or not dependency.startswith("sarj-"):
            continue
        match = _EXACT_DEPENDENCY.fullmatch(dependency)
        if match is None:
            msg = f"compatibility-bundle sibling must use an exact pin: {dependency}"
            raise ValueError(msg)
        requirements.append(RegistryRequirement("pypi", match["name"], match["version"]))

    peers_path = resolved / "packages/lint-configs/src/sarj_lint_configs/configs/eslint.peers.json"
    try:
        peers_value: object = json.loads(peers_path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"could not read compatibility-bundle peers {peers_path}: {exc}"
        raise ValueError(msg) from exc
    peers = string_object_dict(peers_value, label="ESLint peer manifest").get("peers")
    if not is_object_dict(peers):
        msg = f"{peers_path} has no peers object"
        raise ValueError(msg)
    plugin_version = string_object_dict(peers, label="ESLint peers").get("@sarj/eslint-plugin")
    if not isinstance(plugin_version, str) or not plugin_version:
        msg = f"{peers_path} has no exact @sarj/eslint-plugin version"
        raise ValueError(msg)
    requirements.append(RegistryRequirement("npm", "@sarj/eslint-plugin", plugin_version))
    return tuple(sorted(requirements))


def require_lint_config_dependencies(
    root: Path,
    *,
    checker: PublicationChecker = publication_exists,
) -> tuple[RegistryRequirement, ...]:
    """Prove every exact sibling is public before publishing lint-configs."""
    requirements = lint_config_requirements(root)
    for requirement in requirements:
        require_publication(requirement, checker=checker)
    return requirements


def wait_for_lint_config_dependencies(
    root: Path,
    *,
    attempts: int = 6,
    delay: timedelta = timedelta(seconds=10),
    checker: PublicationChecker = publication_exists,
    sleeper: Callable[[float], object] = time.sleep,
) -> tuple[RegistryRequirement, ...]:
    """Wait boundedly for newly published siblings to become registry-visible."""
    if attempts < 1:
        message = "publication attempts must be at least one"
        raise ValueError(message)
    requirements = lint_config_requirements(root)
    missing: tuple[RegistryRequirement, ...] = ()
    for attempt in range(attempts):
        missing = tuple(requirement for requirement in requirements if not checker(requirement))
        if not missing:
            return requirements
        if attempt + 1 < attempts:
            _ = sleeper(delay.total_seconds())
    rendered = ", ".join(f"{requirement.name}@{requirement.version}" for requirement in missing)
    message = f"publications unavailable after {attempts} attempt(s): {rendered}"
    raise ValueError(message)


def main(argv: Sequence[str] | None = None) -> int:
    """Thin automation entry point for the lint-config publication preflight."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=6)
    parser.add_argument(
        "--delay-seconds",
        dest="delay",
        type=_duration_from_seconds,
        default=timedelta(seconds=10),
    )
    args = parser.parse_args(argv, namespace=_Args())
    try:
        requirements = wait_for_lint_config_dependencies(
            args.root,
            attempts=args.attempts,
            delay=args.delay,
        )
    except (OSError, TypeError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    sys.stdout.write(f"verified {len(requirements)} exact compatibility-bundle publications\n")
    return 0


def _duration_from_seconds(value: str) -> timedelta:
    return timedelta(seconds=float(value))


if __name__ == "__main__":
    raise SystemExit(main())
