from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from repo_standards.core.canonical import scope_digest
from repo_standards.policy_sarj import SarjPolicy
from repo_standards.repository import parse_manifest_bytes

from sarj_standards.libs.adoption import repository_baseline, scaffold, service
from sarj_standards.libs.release import rollout


if TYPE_CHECKING:
    from pathlib import Path


_MANIFEST = b'repository_id = "fixture"\ncomponents = []\n'


def _baseline(version: int, *, fingerprints: tuple[str, ...] = ()) -> bytes:
    return (
        json.dumps(
            {
                "fingerprints": fingerprints,
                "policy": "sarj",
                "policy_version": version,
                "repository_id": "fixture",
                "schema_version": 2,
                "scope_digest": scope_digest(parse_manifest_bytes(_MANIFEST)),
            },
            indent="\t",
        )
        .replace("\n", "\r\n")
        .encode("utf-8")
    )


@pytest.mark.parametrize(("before", "after"), [(18, 19), (18, 20), (19, 20)])
@pytest.mark.parametrize(
    "fingerprints",
    [pytest.param((), id="empty-baseline"), pytest.param(("f" * 64, "a" * 64), id="retained-fingerprints")],
)
def test_known_policy_migration_changes_only_the_version_bytes(
    before: int, after: int, fingerprints: tuple[str, ...]
) -> None:
    original = _baseline(before, fingerprints=fingerprints)

    migrated = repository_baseline.migrate(original, _MANIFEST, target_policy_version=after)

    assert migrated == original.replace(f'"policy_version": {before}'.encode(), f'"policy_version": {after}'.encode())
    assert json.loads(migrated)["fingerprints"] == list(fingerprints)


def test_current_repository_baseline_is_preserved_without_reserialization() -> None:
    original = _baseline(19, fingerprints=("b" * 64,))

    assert repository_baseline.migrate(original, _MANIFEST, target_policy_version=19) == original


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_repository_baseline_snapshot_rejects_nonregular_files(tmp_path: Path, kind: str) -> None:
    path = tmp_path / repository_baseline.PATH
    path.parent.mkdir()
    if kind == "directory":
        path.mkdir()
    else:
        path.symlink_to(tmp_path / "missing-target")

    with pytest.raises(OSError, match="regular file"):
        repository_baseline.read_optional(tmp_path)


@pytest.mark.parametrize("invalid", ["repository", "policy", "scope", "schema", "duplicate-key", "unsupported-version"])
def test_unreviewed_or_mismatched_repository_baselines_cannot_migrate(invalid: str) -> None:
    original = _baseline(18)
    replacements = {
        "repository": (b'"fixture"', b'"other"'),
        "policy": (b'"sarj"', b'"other"'),
        "scope": (scope_digest(parse_manifest_bytes(_MANIFEST)).encode(), b"0" * 64),
        "schema": (b'"schema_version": 2', b'"schema_version": 1'),
        "duplicate-key": (b'"policy_version": 18', b'"policy_version": 18, "policy_version": 18'),
        "unsupported-version": (b'"policy_version": 18', b'"policy_version": 17'),
    }
    before, after = replacements[invalid]

    with pytest.raises(ValueError, match=r"baseline|duplicate JSON key"):
        repository_baseline.migrate(original.replace(before, after), _MANIFEST, target_policy_version=19)


def test_setup_plans_the_compatible_migration_without_capturing_new_findings(tmp_path: Path) -> None:
    manifest = tmp_path / ".repo-standards" / "repository.toml"
    manifest.parent.mkdir()
    manifest.write_bytes(_MANIFEST)
    path = tmp_path / repository_baseline.PATH
    original = _baseline(18, fingerprints=("b" * 64,))
    path.write_bytes(original)

    plan = service.plan_init(tmp_path)

    assert not plan.scaffold.errors
    assert path.read_bytes() == original
    planned = dict(plan.scaffold.writes)[path].encode("utf-8")
    assert planned == original.replace(
        b'"policy_version": 18', f'"policy_version": {SarjPolicy.policy_version}'.encode()
    )
    scaffold.apply(plan.scaffold)
    assert path.read_bytes() == planned
    repeated = service.plan_init(tmp_path)
    assert path not in dict(repeated.scaffold.writes)


def test_rollout_allows_only_the_exact_preserving_repository_baseline_delta(tmp_path: Path) -> None:
    manifest = tmp_path / ".repo-standards" / "repository.toml"
    manifest.parent.mkdir()
    manifest.write_bytes(_MANIFEST)
    path = tmp_path / repository_baseline.PATH
    original = _baseline(18, fingerprints=("b" * 64,))
    migrated = repository_baseline.migrate(original, _MANIFEST, target_policy_version=19)
    path.write_bytes(migrated)

    protected = rollout.repository_baseline_migration(tmp_path, original)
    allowed = frozenset(target.relative_to(tmp_path).as_posix() for target in protected)

    assert protected == {path: migrated}
    rollout.reject_unsafe_diff((repository_baseline.PATH,), allowed_baseline_paths=allowed)
    with pytest.raises(rollout.RolloutError, match="protected paths"):
        rollout.reject_unsafe_diff(("nested/" + repository_baseline.PATH,), allowed_baseline_paths=allowed)
    path.write_bytes(migrated.replace(b"b" * 64, b"a" * 64))
    with pytest.raises(rollout.RolloutError, match="fields beyond reviewed policy metadata"):
        rollout.repository_baseline_migration(tmp_path, original)
    with pytest.raises(rollout.RolloutError, match="mutated"):
        rollout.assert_baselines_unchanged(protected)


def test_rollout_cannot_create_or_delete_a_repository_baseline(tmp_path: Path) -> None:
    path = tmp_path / repository_baseline.PATH
    path.parent.mkdir()
    path.write_bytes(_baseline(19))
    with pytest.raises(rollout.RolloutError, match="may not create"):
        rollout.repository_baseline_migration(tmp_path, None)
    path.unlink()
    with pytest.raises(rollout.RolloutError, match="removed"):
        rollout.repository_baseline_migration(tmp_path, _baseline(18))
