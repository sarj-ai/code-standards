"""Authoritative registry proofs for coherent releases and recovery tags."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import timedelta
import json
import math
from pathlib import Path
import re
import sys
import time
import tomllib
from types import MappingProxyType
from typing import TYPE_CHECKING, ClassVar, Final, Literal, Protocol
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from packaging.utils import InvalidSdistFilename, InvalidWheelFilename, parse_sdist_filename, parse_wheel_filename
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field

from sarj_standards.libs.release._values import is_object_dict, is_object_list, string_object_dict
from sarj_standards.libs.release.tags import RELEASE_TARGETS, read_manifest_version


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


RegistryKind = Literal["npm", "pypi"]


@dataclass(frozen=True, slots=True, order=True)
class RegistryRequirement:
    """One exact package version that must exist before dependent publication."""

    registry: RegistryKind
    name: str
    version: str


class _PypiSimpleFile(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    filename: str = Field(min_length=1)


class _PypiSimpleResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", strict=True)

    files: tuple[_PypiSimpleFile, ...]


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
        "standards": ("pypi", "sarj-standards"),
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
    """Query the resolver-facing registry API for one exact version."""
    if requirement.registry == "pypi":
        # uv and pip resolve through the Simple API, so version JSON visibility alone does not make a wheel resolvable.
        url = f"https://pypi.org/simple/{quote(requirement.name, safe='')}/"
        accept = "application/vnd.pypi.simple.v1+json"
    else:
        url = f"https://registry.npmjs.org/{quote(requirement.name, safe='')}/{quote(requirement.version, safe='')}"
        accept = "application/json"
    request = Request(  # ruff: ignore[suspicious-url-open-usage] -- URL is constructed only from fixed HTTPS registry origins.
        url, headers={"Accept": accept}
    )
    try:
        return _request_publication(request, requirement)
    except HTTPError as exc:
        if exc.code == _HTTP_NOT_FOUND:
            return False
        raise


def _request_publication(request: Request, requirement: RegistryRequirement) -> bool:
    with urlopen(request, timeout=15) as response:  # ruff: ignore[suspicious-url-open-usage]  # pyright: ignore[reportAny] -- fixed registry origins
        if response.status != _HTTP_OK:  # pyright: ignore[reportAny]
            return False
        if requirement.registry == "npm":
            return True
        payload: bytes = response.read()  # pyright: ignore[reportAny] -- urllib response is untyped.
        document = _PypiSimpleResponse.model_validate_json(payload)
    return any(_pypi_filename_has_version(item.filename, requirement.version) for item in document.files)


def _pypi_filename_has_version(filename: str, version: str) -> bool:
    """Parse a wheel/source filename and compare its normalized exact version."""
    try:
        expected = Version(version)
        if filename.endswith(".whl"):
            _name, actual, _build, _tags = parse_wheel_filename(filename)
        else:
            _name, actual = parse_sdist_filename(filename)
    except InvalidSdistFilename, InvalidVersion, InvalidWheelFilename:
        return False
    return actual == expected


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
    pyproject = resolved / "packages/standards/pyproject.toml"
    try:
        with pyproject.open("rb") as stream:
            parsed: object = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        msg = f"could not read compatibility-bundle manifest {pyproject}: {exc}"
        raise ValueError(msg) from exc
    project = string_object_dict(parsed, label="standards manifest")
    project_table = project.get("project")
    if not is_object_dict(project_table):
        msg = f"{pyproject} has no project table"
        raise ValueError(msg)
    dependencies = string_object_dict(project_table, label="standards project").get("dependencies")
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

    peers_path = resolved / "packages/standards/src/sarj_standards/configs/eslint.peers.json"
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
    """Prove every exact sibling is public before publishing Standards."""
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
    delay_seconds = delay.total_seconds()
    if not math.isfinite(delay_seconds) or delay_seconds < 0:
        message = "publication retry delay must be finite and non-negative"
        raise ValueError(message)
    requirements = lint_config_requirements(root)
    missing = set(requirements)
    last_errors: dict[RegistryRequirement, str] = {}
    for attempt in range(attempts):
        for requirement in tuple(sorted(missing)):
            try:
                available = checker(requirement)
            except OSError as exc:
                last_errors[requirement] = f"{type(exc).__name__}: {exc}"
                continue
            if available:
                missing.remove(requirement)
                last_errors.pop(requirement, None)
        if not missing:
            return requirements
        if attempt + 1 < attempts:
            _ = sleeper(delay_seconds)
    rendered = ", ".join(
        f"{requirement.name}@{requirement.version}"
        + (f" ({last_errors[requirement]})" if requirement in last_errors else "")
        for requirement in sorted(missing)
    )
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
