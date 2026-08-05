"""Minimum-release-age policy for npm lockfiles."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from typing import TYPE_CHECKING, Protocol, Self
from urllib.parse import quote
from urllib.request import Request, urlopen

from sarj_lint_configs.libs.release._values import is_object_dict, string_object_dict


if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

_SCOPED_PACKAGE_PARTS = 2


class PackumentFetcher(Protocol):
    """Fetch one npm package metadata document."""

    def __call__(self, package_name: str, /) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True, order=True)
class PackageIdentity:
    """A unique registry package version represented in a lockfile."""

    name: str
    version: str


@dataclass(frozen=True, slots=True)
class ReleaseAgePolicy:
    """Minimum package age and explicit package/version exceptions."""

    minimum_age: timedelta = timedelta(days=14)
    exclusions: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.minimum_age < timedelta(0):
            msg = "minimum release age must be non-negative"
            raise ValueError(msg)

    @classmethod
    def from_strings(cls, days_value: str | None, exclusions: str | None) -> Self:
        """Parse CLI/environment values with the former script's defaults."""
        raw_days = "14" if days_value is None else days_value
        try:
            parsed_days = int(raw_days, 10)
        except ValueError as exc:
            msg = "MIN_RELEASE_AGE_DAYS must be a non-negative integer"
            raise ValueError(msg) from exc
        if parsed_days < 0 or str(parsed_days) != raw_days.strip():
            msg = "MIN_RELEASE_AGE_DAYS must be a non-negative integer"
            raise ValueError(msg)
        parsed_exclusions = frozenset(value for item in (exclusions or "").split(",") if (value := item.strip()))
        return cls(timedelta(days=parsed_days), parsed_exclusions)


@dataclass(frozen=True, slots=True, order=True)
class ReleaseAgeFailure:
    """A locked version that is too new or lacks publication metadata."""

    identity: PackageIdentity
    detail: str

    def __str__(self) -> str:
        return f"{self.identity.name}@{self.identity.version}: {self.detail}"


@dataclass(frozen=True, slots=True)
class ReleaseAgeReport:
    """Deterministic result of checking all applicable lockfile packages."""

    checked: tuple[PackageIdentity, ...]
    failures: tuple[ReleaseAgeFailure, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


def locked_registry_packages(lockfile: Path, policy: ReleaseAgePolicy) -> tuple[PackageIdentity, ...]:
    """Extract unique npm-registry package versions from a package-lock file."""
    packages_value = _load_object(lockfile).get("packages")
    if packages_value is None:
        return ()
    packages = string_object_dict(packages_value, label="package-lock packages")
    identities: set[PackageIdentity] = set()
    for lock_path, metadata_value in packages.items():
        name = _package_name(lock_path)
        if name is None or not is_object_dict(metadata_value):
            continue
        metadata = string_object_dict(metadata_value, label=f"package metadata for {lock_path}")
        version = metadata.get("version")
        resolved = metadata.get("resolved")
        if not isinstance(version, str) or not version:
            continue
        if isinstance(resolved, str) and not resolved.startswith("https://registry.npmjs.org/"):
            continue
        identity = PackageIdentity(name, version)
        if name not in policy.exclusions and f"{name}@{version}" not in policy.exclusions:
            identities.add(identity)
    return tuple(sorted(identities))


def _load_object(path: Path) -> dict[str, object]:
    try:
        untyped: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"could not read npm lockfile {path}: {exc}"
        raise ValueError(msg) from exc
    return string_object_dict(untyped, label="npm lockfile")


def _package_name(lock_path: str) -> str | None:
    marker = "node_modules/"
    if marker not in lock_path:
        return None
    tail = lock_path.rpartition(marker)[2]
    parts = tail.split("/")
    if not parts[0]:
        return None
    if parts[0].startswith("@"):
        return "/".join(parts[:_SCOPED_PACKAGE_PARTS]) if len(parts) >= _SCOPED_PACKAGE_PARTS and parts[1] else None
    return parts[0]


def fetch_npm_packument(package_name: str) -> Mapping[str, object]:
    """Fetch package metadata from the fixed public npm registry origin."""
    url = f"https://registry.npmjs.org/{quote(package_name, safe='')}"
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=15) as response:  # ruff: ignore[suspicious-url-open-usage]  # pyright: ignore[reportAny] -- fixed trusted origin
        untyped: object = json.load(response)  # pyright: ignore[reportAny]
    return string_object_dict(untyped, label=f"npm registry response for {package_name}")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def check_lockfile_release_age(
    lockfile: Path,
    policy: ReleaseAgePolicy | None = None,
    *,
    fetcher: PackumentFetcher = fetch_npm_packument,
    clock: Callable[[], datetime] = _utc_now,
    concurrency: int = 12,
) -> ReleaseAgeReport:
    """Check npm publication age concurrently with injectable I/O and time."""
    if concurrency < 1:
        msg = "release-age concurrency must be at least one"
        raise ValueError(msg)
    now = clock()
    if now.tzinfo is None:
        msg = "release-age clock must return a timezone-aware datetime"
        raise ValueError(msg)
    now = now.astimezone(UTC)
    effective_policy = ReleaseAgePolicy() if policy is None else policy
    identities = locked_registry_packages(lockfile, effective_policy)
    cutoff = now - effective_policy.minimum_age

    def check_one(identity: PackageIdentity) -> ReleaseAgeFailure | None:
        return _check_identity(identity, cutoff=cutoff, now=now, fetcher=fetcher)

    with ThreadPoolExecutor(max_workers=min(concurrency, max(1, len(identities)))) as executor:
        checked = executor.map(check_one, identities)
        failures = tuple(sorted(failure for failure in checked if failure is not None))
    return ReleaseAgeReport(identities, failures)


def _check_identity(
    identity: PackageIdentity,
    *,
    cutoff: datetime,
    now: datetime,
    fetcher: PackumentFetcher,
) -> ReleaseAgeFailure | None:
    available, published = _publication_time(fetcher(identity.name), identity.version)
    if not available:
        return ReleaseAgeFailure(identity, "publication time unavailable")
    if published is None:
        return ReleaseAgeFailure(identity, "unknown days old")
    if published > cutoff:
        age_days = (now - published).total_seconds() / timedelta(days=1).total_seconds()
        return ReleaseAgeFailure(identity, f"{age_days:.1f} days old")
    return None


def _publication_time(packument: Mapping[str, object], version: str) -> tuple[bool, datetime | None]:
    time_value = packument.get("time")
    if not is_object_dict(time_value):
        return False, None
    published = string_object_dict(time_value, label="npm publication times").get(version)
    if not isinstance(published, str):
        return False, None
    try:
        parsed = datetime.fromisoformat(published)
    except ValueError:
        return True, None
    return True, parsed.astimezone(UTC) if parsed.tzinfo is not None else None
