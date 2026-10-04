from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.release import (
    PackageIdentity,
    ReleaseAgePolicy,
    check_lockfile_release_age,
    load_exact_exclusions,
    locked_registry_packages,
)


if TYPE_CHECKING:
    from pathlib import Path


def _lockfile(tmp_path: Path, packages: dict[str, object]) -> Path:
    path = tmp_path / "package-lock.json"
    path.write_text(json.dumps({"packages": packages}), encoding="utf-8")
    return path


def test_locked_registry_packages_deduplicates_and_supports_scopes(tmp_path: Path) -> None:
    lockfile = _lockfile(
        tmp_path,
        {
            "": {"name": "root"},
            "node_modules/plain": {"version": "1.0.0", "resolved": "https://registry.npmjs.org/plain/-/plain.tgz"},
            "nested/node_modules/plain": {"version": "1.0.0"},
            "node_modules/@scope/pkg": {"version": "2.0.0"},
        },
    )

    assert locked_registry_packages(lockfile, ReleaseAgePolicy()) == (
        PackageIdentity("@scope/pkg", "2.0.0"),
        PackageIdentity("plain", "1.0.0"),
    )


def test_locked_registry_packages_rejects_non_npm_registry_artifact(tmp_path: Path) -> None:
    lockfile = _lockfile(
        tmp_path,
        {
            "node_modules/private": {
                "version": "3.0.0",
                "resolved": "https://packages.example/private.tgz",
            },
        },
    )

    with pytest.raises(ValueError, match=r"resolves outside registry\.npmjs\.org"):
        locked_registry_packages(lockfile, ReleaseAgePolicy())


def test_lockfile_release_age_checks_alias_targets(tmp_path: Path) -> None:
    lockfile = _lockfile(
        tmp_path,
        {
            "node_modules/@typescript/native": {"name": "typescript", "version": "7.0.2"},
            "node_modules/typescript": {"name": "@typescript/typescript6", "version": "6.0.2"},
            "node_modules/@typescript/old": {"name": "typescript", "version": "6.0.3"},
        },
    )
    publications = {
        "typescript": {"time": {"7.0.2": "2025-01-25T12:00:00Z", "6.0.3": "2025-01-01T00:00:00Z"}},
        "@typescript/typescript6": {"time": {"6.0.2": "2025-01-01T00:00:00Z"}},
    }

    report = check_lockfile_release_age(
        lockfile,
        fetcher=publications.__getitem__,
        clock=lambda: datetime(2025, 2, 1, tzinfo=UTC),
    )

    assert report.checked == (
        PackageIdentity("@typescript/typescript6", "6.0.2"),
        PackageIdentity("typescript", "6.0.3"),
        PackageIdentity("typescript", "7.0.2"),
    )
    assert [str(failure) for failure in report.failures] == ["typescript@7.0.2: 6.5 days old"]


@pytest.mark.parametrize(("exclusion", "excluded"), [("typescript@7.0.2", True), ("@typescript/native@7.0.2", False)])
def test_alias_release_age_exclusions_use_registry_identity(tmp_path: Path, exclusion: str, excluded: bool) -> None:
    lockfile = _lockfile(tmp_path, {"node_modules/@typescript/native": {"name": "typescript", "version": "7.0.2"}})

    packages = locked_registry_packages(lockfile, ReleaseAgePolicy(exclusions=frozenset({exclusion})))

    assert packages == (() if excluded else (PackageIdentity("typescript", "7.0.2"),))


def test_locked_registry_packages_applies_name_and_version_exclusions(tmp_path: Path) -> None:
    lockfile = _lockfile(
        tmp_path,
        {
            "node_modules/a": {"version": "1.0.0"},
            "node_modules/b": {"version": "2.0.0"},
        },
    )
    policy = ReleaseAgePolicy(exclusions=frozenset({"a", "b@2.0.0"}))

    assert locked_registry_packages(lockfile, policy) == ()


def test_load_exact_exclusions_accepts_comments_and_scoped_packages(tmp_path: Path) -> None:
    path = tmp_path / "exclusions.txt"
    path.write_text("# temporary\nplain@1.2.3 # reason\n@scope/pkg@4.5.6\n", encoding="utf-8")

    assert load_exact_exclusions(path) == frozenset({"plain@1.2.3", "@scope/pkg@4.5.6"})


@pytest.mark.parametrize("value", ["plain", "@scope@1.0.0", "plain@", "@1.0.0"])
def test_load_exact_exclusions_rejects_non_exact_entries(tmp_path: Path, value: str) -> None:
    path = tmp_path / "exclusions.txt"
    path.write_text(f"{value}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="expected an exact package@version"):
        load_exact_exclusions(path)


def test_check_lockfile_release_age_uses_injected_clock_and_fetcher(tmp_path: Path) -> None:
    lockfile = _lockfile(
        tmp_path,
        {
            "node_modules/old": {"version": "1.0.0"},
            "node_modules/new": {"version": "2.0.0"},
        },
    )
    publications = {
        "old": {"time": {"1.0.0": "2025-01-01T00:00:00Z"}},
        "new": {"time": {"2.0.0": "2025-01-25T12:00:00Z"}},
    }

    report = check_lockfile_release_age(
        lockfile,
        ReleaseAgePolicy(minimum_age=timedelta(days=14)),
        fetcher=publications.__getitem__,
        clock=lambda: datetime(2025, 2, 1, tzinfo=UTC),
    )

    assert not report.passed
    assert [str(failure) for failure in report.failures] == ["new@2.0.0: 6.5 days old"]


def test_check_lockfile_release_age_reports_missing_publication_time(tmp_path: Path) -> None:
    lockfile = _lockfile(tmp_path, {"node_modules/a": {"version": "1.0.0"}})

    report = check_lockfile_release_age(
        lockfile,
        fetcher=lambda _name: {"time": {}},
        clock=lambda: datetime(2025, 2, 1, tzinfo=UTC),
    )

    assert [str(failure) for failure in report.failures] == ["a@1.0.0: publication time unavailable"]


def test_check_lockfile_release_age_reports_invalid_publication_time(tmp_path: Path) -> None:
    lockfile = _lockfile(tmp_path, {"node_modules/a": {"version": "1.0.0"}})

    report = check_lockfile_release_age(
        lockfile,
        fetcher=lambda _name: {"time": {"1.0.0": "not-a-date"}},
        clock=lambda: datetime(2025, 2, 1, tzinfo=UTC),
    )

    assert [str(failure) for failure in report.failures] == ["a@1.0.0: unknown days old"]


@pytest.mark.parametrize("days", ["-1", "1.5", "nope", " 01 "])
def test_release_age_policy_rejects_invalid_days(days: str) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        ReleaseAgePolicy.from_strings(days, None)


def test_release_age_policy_parses_trimmed_exclusions() -> None:
    policy = ReleaseAgePolicy.from_strings(None, " a, @scope/pkg@1.0.0, ,")

    assert policy == ReleaseAgePolicy(timedelta(days=14), frozenset({"a", "@scope/pkg@1.0.0"}))


def test_check_lockfile_release_age_rejects_naive_clock(tmp_path: Path) -> None:
    lockfile = _lockfile(tmp_path, {})
    naive = datetime(2025, 1, 1, tzinfo=UTC).replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        check_lockfile_release_age(lockfile, clock=lambda: naive)


def _workspace_lockfile(tmp_path: Path, *, include_external: bool = False) -> Path:
    native: dict[str, object] = {
        "name": "@control/native",
        "version": "1.0.0",
        "dependencies": {"runtime": "1.0.0"},
        "devDependencies": {"build": "1.0.0"},
        "optionalDependencies": {"optional": "1.0.0"},
        "peerDependencies": {"peer": "1.0.0"},
    }
    if include_external:
        native["dependencies"] = {"runtime": "1.0.0", "docs-source": "1.0.0"}
    docs: dict[str, object] = {"name": "docs", "version": "1.0.0", "dependencies": {"docs-source": "1.0.0"}}
    root = {"name": "control", "version": "1.0.0", "private": True, "workspaces": ["packages/native", "apps/docs"]}
    (tmp_path / "package.json").write_text(json.dumps(root), encoding="utf-8")
    for location, metadata in (("packages/native", native), ("apps/docs", docs)):
        directory = tmp_path / location
        directory.mkdir(parents=True)
        (directory / "package.json").write_text(json.dumps(metadata), encoding="utf-8")
    packages: dict[str, object] = {
        "": root,
        "packages/native": native,
        "apps/docs": docs,
        "node_modules/@control/native": {"resolved": "packages/native", "link": True},
        "node_modules/docs": {"resolved": "apps/docs", "link": True},
        "node_modules/docs-source": {
            "version": "1.0.0",
            "resolved": "https://codeload.github.com/control/docs/tar.gz/exact",
        },
    }
    for name in ("runtime", "transitive", "build", "optional", "peer"):
        metadata: dict[str, object] = {
            "version": "1.0.0",
            "resolved": f"https://registry.npmjs.org/{name}/-/{name}-1.0.0.tgz",
        }
        if name == "runtime":
            metadata["dependencies"] = {"transitive": "1.0.0"}
        packages[f"node_modules/{name}"] = metadata
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(
        json.dumps({"name": "control", "version": "1.0.0", "lockfileVersion": 3, "packages": packages}),
        encoding="utf-8",
    )
    return lockfile


def test_real_npm_workspace_closure_checks_runtime_build_peer_optional_and_transitive_age(tmp_path: Path) -> None:
    lockfile = _workspace_lockfile(tmp_path)
    report = check_lockfile_release_age(
        lockfile,
        workspace="packages/native",
        fetcher=lambda name: {
            "time": {"1.0.0": "2025-01-25T12:00:00Z" if name == "transitive" else "2025-01-01T00:00:00Z"}
        },
        clock=lambda: datetime(2025, 2, 1, tzinfo=UTC),
    )
    assert {identity.name for identity in report.checked} == {"runtime", "build", "peer", "optional", "transitive"}
    assert [str(failure) for failure in report.failures] == ["transitive@1.0.0: 6.5 days old"]
    with pytest.raises(ValueError, match=r"resolves outside registry\.npmjs\.org"):
        locked_registry_packages(lockfile, ReleaseAgePolicy())


def test_real_npm_workspace_closure_rejects_reachable_nonregistry_source(tmp_path: Path) -> None:
    lockfile = _workspace_lockfile(tmp_path, include_external=True)
    with pytest.raises(ValueError, match=r"docs-source@1.0.0 resolves outside registry\.npmjs\.org"):
        locked_registry_packages(lockfile, ReleaseAgePolicy(), workspace="packages/native")
