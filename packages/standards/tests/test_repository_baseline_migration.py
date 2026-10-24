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


@pytest.mark.parametrize(("before", "after"), [(18, 19), (18, 20), (19, 20), (25, 26), (25, 27), (26, 27)])
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


@pytest.mark.parametrize(
    "fingerprints",
    [
        pytest.param((), id="empty-warning-ratchet"),
        pytest.param(("f" * 64, "a" * 64), id="retained-warning-debt"),
    ],
)
def test_policy26_preserves_warning_ratchets_without_recapturing_findings(
    fingerprints: tuple[str, ...],
) -> None:
    original = _baseline(25, fingerprints=fingerprints).replace(
        b'"schema_version": 2', b'"schema_version": 2,\r\n\t"include_warnings": true'
    )

    migrated = repository_baseline.migrate(original, _MANIFEST, target_policy_version=26)

    assert migrated == original.replace(b'"policy_version": 25', b'"policy_version": 26')


@pytest.mark.parametrize("before", [25, 26])
@pytest.mark.parametrize("include_warnings", [False, True])
@pytest.mark.parametrize(
    "fingerprints",
    [
        pytest.param((), id="empty-baseline"),
        pytest.param(("f" * 64, "a" * 64), id="retained-fingerprints"),
    ],
)
def test_policy27_retains_existing_debt_and_explicit_warning_choice(
    before: int, *, include_warnings: bool, fingerprints: tuple[str, ...]
) -> None:
    original = _baseline(before, fingerprints=fingerprints).replace(
        b'"schema_version": 2',
        b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
    )

    migrated = repository_baseline.migrate(original, _MANIFEST, target_policy_version=27)

    assert migrated == original.replace(f'"policy_version": {before}'.encode(), b'"policy_version": 27')


@pytest.mark.parametrize(("before", "after"), [(22, 26), (24, 26), (26, 25), (24, 27), (27, 26), (26, 28), (27, 28)])
def test_policy26_migration_does_not_allow_unreviewed_jumps_or_downgrades(before: int, after: int) -> None:
    original = _baseline(before, fingerprints=("b" * 64,))

    with pytest.raises(ValueError, match="requires a separately reviewed compatibility decision"):
        repository_baseline.migrate(original, _MANIFEST, target_policy_version=after)


@pytest.mark.parametrize("include_warnings", [None, False, True])
def test_policy28_migrates_empty_baselines_without_changing_the_warning_ratchet(
    include_warnings: bool | None,
) -> None:
    original = _baseline(27)
    if include_warnings is not None:
        original = original.replace(
            b'"schema_version": 2',
            b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
        )

    migrated = repository_baseline.migrate(original, _MANIFEST, target_policy_version=28)

    assert migrated == original.replace(b'"policy_version": 27', b'"policy_version": 28')


@pytest.mark.parametrize(("before", "after"), [(26, 28), (28, 27), (28, 29)])
def test_empty_baselines_do_not_authorize_other_policy_transitions(before: int, after: int) -> None:
    with pytest.raises(ValueError, match="requires a separately reviewed compatibility decision"):
        repository_baseline.migrate(_baseline(before), _MANIFEST, target_policy_version=after)


def test_setup_plans_and_applies_the_empty_policy27_baseline_migration(tmp_path: Path) -> None:
    manifest = tmp_path / ".repo-standards" / "repository.toml"
    manifest.parent.mkdir()
    manifest.write_bytes(_MANIFEST)
    path = tmp_path / repository_baseline.PATH
    original = _baseline(27)
    path.write_bytes(original)

    plan = service.plan_init(tmp_path)

    assert not plan.scaffold.errors
    assert (
        dict(plan.scaffold.writes)[path] == original.replace(b'"policy_version": 27', b'"policy_version": 28').decode()
    )
    assert path.read_bytes() == original
    scaffold.apply(plan.scaffold)
    assert path.read_bytes() == original.replace(b'"policy_version": 27', b'"policy_version": 28')
    assert path not in dict(service.plan_init(tmp_path).scaffold.writes)


@pytest.mark.parametrize("mutation", ["warning-ratchet", "accepted-debt", "scope"])
def test_rollout_accepts_the_empty_migration_and_rejects_other_baseline_changes(tmp_path: Path, mutation: str) -> None:
    manifest = tmp_path / ".repo-standards" / "repository.toml"
    manifest.parent.mkdir()
    manifest.write_bytes(_MANIFEST)
    path = tmp_path / repository_baseline.PATH
    original = _baseline(27).replace(b'"schema_version": 2', b'"schema_version": 2,\r\n\t"include_warnings": true')
    migrated = repository_baseline.migrate(original, _MANIFEST, target_policy_version=28)
    path.write_bytes(migrated)

    assert rollout.repository_baseline_migration(tmp_path, original) == {path: migrated}

    match mutation:
        case "warning-ratchet":
            changed = migrated.replace(b'"include_warnings": true', b'"include_warnings": false')
        case "accepted-debt":
            changed = migrated.replace(b'"fingerprints": []', b'"fingerprints": ["' + b"b" * 64 + b'"]')
        case _:
            assert mutation == "scope"
            changed = migrated.replace(scope_digest(parse_manifest_bytes(_MANIFEST)).encode(), b"0" * 64)
    path.write_bytes(changed)
    with pytest.raises(rollout.RolloutError, match="fields beyond reviewed policy metadata"):
        rollout.repository_baseline_migration(tmp_path, original)


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


@pytest.mark.parametrize("version", [18, 19, 20, 25, 26, 27])
def test_setup_rejects_unreviewed_policy_changes_without_mutating_baselines(tmp_path: Path, version: int) -> None:
    manifest = tmp_path / ".repo-standards" / "repository.toml"
    manifest.parent.mkdir()
    manifest.write_bytes(_MANIFEST)
    path = tmp_path / repository_baseline.PATH
    original = _baseline(version, fingerprints=("b" * 64,))
    path.write_bytes(original)

    plan = service.plan_init(tmp_path)

    assert any("requires a separately reviewed compatibility decision" in error for error in plan.scaffold.errors)
    assert path not in dict(plan.scaffold.writes)
    assert path.read_bytes() == original
    result = service.apply_init(plan, install=False)
    assert result.status == 2
    assert result.failure is service.InitFailure.APPLY
    assert path.read_bytes() == original


def test_setup_preserves_current_policy_baselines_without_recapturing_findings(tmp_path: Path) -> None:
    manifest = tmp_path / ".repo-standards" / "repository.toml"
    manifest.parent.mkdir()
    manifest.write_bytes(_MANIFEST)
    path = tmp_path / repository_baseline.PATH
    original = _baseline(SarjPolicy.policy_version, fingerprints=("b" * 64,))
    path.write_bytes(original)

    plan = service.plan_init(tmp_path)

    assert not plan.scaffold.errors
    assert path not in dict(plan.scaffold.writes)
    assert path.read_bytes() == original
    scaffold.apply(plan.scaffold)
    assert path.read_bytes() == original
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
