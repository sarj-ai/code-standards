from __future__ import annotations

import json
import re
import subprocess
from typing import TYPE_CHECKING

import pytest
from repo_standards.core.canonical import scope_digest
from repo_standards.policy_sarj import SarjPolicy
from repo_standards.repository import RepositoryAnalysisRequest, analyze_repository, parse_manifest_bytes

from sarj_standards.libs.adoption import repository_baseline, scaffold, service
from sarj_standards.libs.release import rollout


if TYPE_CHECKING:
    from pathlib import Path


_MANIFEST = b'repository_id = "fixture"\ncomponents = []\n'

_COMMIT_ONLY_MANIFEST = _MANIFEST + b'[pull_request.commit_history]\nadvisory_base_ref = "main"\n'
_REVIEW_MANIFEST = _COMMIT_ONLY_MANIFEST + (
    b"[pull_request.review_policy]\n"
    b"zero_review_below_counted_lines = 50\n"
    b"two_reviews_above_counted_lines = 500\n"
    b"migration_roots = []\n"
    b'required_checks = ["Standards"]\n'
    b'required_body_sections = ["Test evidence"]\n'
)


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


@pytest.mark.parametrize(
    ("before", "after"),
    [(18, 19), (18, 20), (19, 20), (25, 26), (25, 27), (26, 27), (28, 29), (32, 33), (33, 34), (34, 35)],
)
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


def test_policy33_preserves_nonempty_warning_debt_and_metadata() -> None:
    original = _baseline(32, fingerprints=("f" * 64, "a" * 64)).replace(
        b'"schema_version": 2', b'"schema_version": 2,\r\n\t"include_warnings": true'
    )

    migrated = repository_baseline.migrate(original, _MANIFEST, target_policy_version=33)

    assert migrated == original.replace(b'"policy_version": 32', b'"policy_version": 33')


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


@pytest.mark.parametrize(
    ("before", "after"),
    [(22, 26), (24, 26), (26, 25), (24, 27), (27, 26), (26, 28), (27, 28), (27, 29), (25, 29), (26, 29)],
)
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


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (26, 28),
        (28, 27),
        (29, 28),
        (18, 33),
        (32, 36),
        (34, 33),
        (30, 29),
        (25, 29),
        (26, 29),
        (25, 30),
        (26, 30),
    ],
)
def test_empty_baselines_do_not_authorize_other_policy_transitions(before: int, after: int) -> None:
    with pytest.raises(ValueError, match="requires a separately reviewed compatibility decision"):
        repository_baseline.migrate(_baseline(before), _MANIFEST, target_policy_version=after)


@pytest.mark.parametrize("include_warnings", [None, False, True])
@pytest.mark.parametrize(
    "fingerprints",
    [pytest.param((), id="empty-debt"), pytest.param(("a" * 64, "f" * 64), id="existing-debt")],
)
@pytest.mark.parametrize("target", [29, 30], ids=["policy29", "policy30"])
def test_policy28_preserves_existing_debt_and_warning_choice(
    include_warnings: bool | None, fingerprints: tuple[str, ...], target: int
) -> None:
    original = _baseline(28, fingerprints=fingerprints)
    if include_warnings is not None:
        original = original.replace(
            b'"schema_version": 2',
            b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
        )

    migrated = repository_baseline.migrate(original, _MANIFEST, target_policy_version=target)

    assert migrated == original.replace(b'"policy_version": 28', f'"policy_version": {target}'.encode())


@pytest.mark.parametrize("include_warnings", [None, False, True])
def test_empty_policy27_to29_equals_the_two_reviewed_steps(include_warnings: bool | None) -> None:
    original = _baseline(27)
    if include_warnings is not None:
        original = original.replace(
            b'"schema_version": 2',
            b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
        )

    intermediate = repository_baseline.migrate(original, _MANIFEST, target_policy_version=28)
    composed = repository_baseline.migrate(intermediate, _MANIFEST, target_policy_version=29)
    direct = repository_baseline.migrate(original, _MANIFEST, target_policy_version=29)

    assert direct == composed == original.replace(b'"policy_version": 27', b'"policy_version": 29')


@pytest.mark.parametrize("before", [27, 28, 29])
@pytest.mark.parametrize("include_warnings", [None, False, True])
def test_empty_policy30_migration_equals_the_explicit_reviewed_steps(
    before: int, include_warnings: bool | None
) -> None:
    original = _baseline(before)
    if include_warnings is not None:
        original = original.replace(
            b'"schema_version": 2',
            b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
        )
    composed = original
    for version in range(before + 1, 31):
        composed = repository_baseline.migrate(composed, _MANIFEST, target_policy_version=version)

    direct = repository_baseline.migrate(original, _MANIFEST, target_policy_version=30)

    assert direct == composed == original.replace(f'"policy_version": {before}'.encode(), b'"policy_version": 30')


@pytest.mark.parametrize("include_warnings", [None, False, True])
def test_policy30_keeps_nonempty_policy27_debt_rejected(include_warnings: bool | None) -> None:
    original = _baseline(27, fingerprints=("b" * 64,))
    if include_warnings is not None:
        original = original.replace(
            b'"schema_version": 2',
            b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
        )

    with pytest.raises(ValueError, match="requires a separately reviewed compatibility decision"):
        repository_baseline.migrate(original, _MANIFEST, target_policy_version=30)


@pytest.mark.parametrize("include_warnings", [None, False])
def test_policy30_preserves_error_only_policy29_debt(include_warnings: bool | None) -> None:
    original = _baseline(29, fingerprints=("a" * 64, "f" * 64))
    if include_warnings is not None:
        original = original.replace(b'"schema_version": 2', b'"schema_version": 2,\r\n\t"include_warnings": false')

    migrated = repository_baseline.migrate(original, _MANIFEST, target_policy_version=30)

    assert migrated == original.replace(b'"policy_version": 29', b'"policy_version": 30')


def test_policy30_rejects_nonempty_policy29_warning_debt() -> None:
    original = _baseline(29, fingerprints=("b" * 64,)).replace(
        b'"schema_version": 2', b'"schema_version": 2,\r\n\t"include_warnings": true'
    )

    with pytest.raises(ValueError, match="requires a separately reviewed compatibility decision"):
        repository_baseline.migrate(original, _MANIFEST, target_policy_version=30)


@pytest.mark.parametrize("warning_choice", [b"null", b"0", b'"false"', b"[]"])
def test_policy30_does_not_treat_malformed_warning_choices_as_error_only(warning_choice: bytes) -> None:
    original = _baseline(29, fingerprints=("b" * 64,)).replace(
        b'"schema_version": 2', b'"schema_version": 2,\r\n\t"include_warnings": ' + warning_choice
    )

    with pytest.raises(ValueError, match="baseline"):
        repository_baseline.migrate(original, _MANIFEST, target_policy_version=30)


@pytest.mark.parametrize("before", [28, 30], ids=["before-migration-warning", "before-image-rule"])
@pytest.mark.parametrize("after", [31, 32], ids=["image-warning", "image-error"])
@pytest.mark.parametrize("include_warnings", [False, True], ids=["error-debt", "warning-debt"])
def test_image_policy_preserves_prior_debt_and_warning_choice(
    before: int, after: int, *, include_warnings: bool
) -> None:
    original = _baseline(before, fingerprints=("a" * 64, "f" * 64)).replace(
        b'"schema_version": 2',
        b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
    )

    migrated = repository_baseline.migrate(original, _MANIFEST, target_policy_version=after)

    assert migrated == original.replace(f'"policy_version": {before}'.encode(), f'"policy_version": {after}'.encode())


@pytest.mark.parametrize("before", [29, 31], ids=["migration-warning", "image-warning"])
@pytest.mark.parametrize("include_warnings", [None, False], ids=["legacy-error-only", "explicit-error-only"])
def test_image_error_policy_preserves_error_only_debt(before: int, include_warnings: bool | None) -> None:
    original = _baseline(before, fingerprints=("a" * 64, "f" * 64))
    if include_warnings is not None:
        original = original.replace(b'"schema_version": 2', b'"schema_version": 2,\r\n\t"include_warnings": false')

    migrated = repository_baseline.migrate(original, _MANIFEST, target_policy_version=32)

    assert migrated == original.replace(f'"policy_version": {before}'.encode(), b'"policy_version": 32')


@pytest.mark.parametrize(
    ("before", "after"),
    [
        pytest.param(29, 31, id="migration-warning-to-image-warning"),
        pytest.param(29, 32, id="migration-warning-to-image-error"),
        pytest.param(31, 32, id="image-warning-to-image-error"),
    ],
)
def test_image_policy_rejects_obsolete_nonempty_warning_debt(before: int, after: int) -> None:
    original = _baseline(before, fingerprints=("b" * 64,)).replace(
        b'"schema_version": 2', b'"schema_version": 2,\r\n\t"include_warnings": true'
    )

    with pytest.raises(ValueError, match="requires a separately reviewed compatibility decision"):
        repository_baseline.migrate(original, _MANIFEST, target_policy_version=after)


@pytest.mark.parametrize(
    "before",
    [27, 28, 29, 30, 31, 32],
    ids=["policy27", "policy28", "policy29", "policy30", "policy31", "policy32"],
)
@pytest.mark.parametrize("include_warnings", [None, False, True], ids=["legacy-errors", "errors", "warnings"])
def test_image_error_policy_composes_reviewed_empty_migrations(before: int, include_warnings: bool | None) -> None:
    original = _baseline(before)
    if include_warnings is not None:
        original = original.replace(
            b'"schema_version": 2',
            b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
        )
    composed = original
    for version in range(before + 1, 33):
        composed = repository_baseline.migrate(composed, _MANIFEST, target_policy_version=version)

    direct = repository_baseline.migrate(original, _MANIFEST, target_policy_version=32)

    assert direct == composed == original.replace(f'"policy_version": {before}'.encode(), b'"policy_version": 32')


@pytest.mark.parametrize("before", [27, 28, 29, 30, 31, 32])
@pytest.mark.parametrize("include_warnings", [None, False, True], ids=["legacy", "errors", "warnings"])
def test_policy33_composes_existing_policy32_migration(before: int, include_warnings: bool | None) -> None:
    original = _baseline(before)
    if include_warnings is not None:
        original = original.replace(
            b'"schema_version": 2',
            b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
        )

    through_32 = repository_baseline.migrate(original, _MANIFEST, target_policy_version=32)
    composed = repository_baseline.migrate(through_32, _MANIFEST, target_policy_version=33)
    direct = repository_baseline.migrate(original, _MANIFEST, target_policy_version=33)

    assert direct == composed == original.replace(f'"policy_version": {before}'.encode(), b'"policy_version": 33')


@pytest.mark.parametrize("before", [27, 28, 29, 30, 31])
@pytest.mark.parametrize("include_warnings", [None, False, True], ids=["legacy", "errors", "warnings"])
def test_policy33_retains_policy32_debt_guards(before: int, include_warnings: bool | None) -> None:
    original = _baseline(before, fingerprints=("b" * 64,))
    if include_warnings is not None:
        original = original.replace(
            b'"schema_version": 2',
            b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
        )

    try:
        expected = repository_baseline.migrate(original, _MANIFEST, target_policy_version=32)
    except ValueError as intermediate_error:
        expected_error = str(intermediate_error)
    else:
        direct = repository_baseline.migrate(original, _MANIFEST, target_policy_version=33)
        assert direct == expected.replace(b'"policy_version": 32', b'"policy_version": 33')
        return
    with pytest.raises(ValueError, match=re.escape(expected_error)) as raised:
        repository_baseline.migrate(original, _MANIFEST, target_policy_version=33)
    assert str(raised.value) == expected_error


@pytest.mark.parametrize(
    ("before", "include_warnings"),
    [(28, True), (29, False), (30, True), (31, False), (32, True)],
)
def test_policy33_composes_compatible_nonempty_debt(before: int, include_warnings: bool) -> None:
    original = _baseline(before, fingerprints=("a" * 64, "f" * 64)).replace(
        b'"schema_version": 2',
        b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
    )

    through_32 = repository_baseline.migrate(original, _MANIFEST, target_policy_version=32)
    composed = repository_baseline.migrate(through_32, _MANIFEST, target_policy_version=33)
    direct = repository_baseline.migrate(original, _MANIFEST, target_policy_version=33)

    assert direct == composed == original.replace(f'"policy_version": {before}'.encode(), b'"policy_version": 33')


@pytest.mark.parametrize(
    "before", [27, 28, 29, 30, 31, 32], ids=["policy27", "policy28", "policy29", "policy30", "policy31", "policy32"]
)
def test_setup_plans_and_applies_the_current_compatible_baseline_migration(tmp_path: Path, before: int) -> None:
    manifest = tmp_path / ".repo-standards" / "repository.toml"
    manifest.parent.mkdir()
    manifest.write_bytes(_MANIFEST)
    path = tmp_path / repository_baseline.PATH
    original = _baseline(before)
    path.write_bytes(original)

    plan = service.plan_init(tmp_path)

    assert not plan.scaffold.errors
    assert (
        dict(plan.scaffold.writes)[path]
        == original.replace(
            f'"policy_version": {before}'.encode(), f'"policy_version": {SarjPolicy.policy_version}'.encode()
        ).decode()
    )
    assert path.read_bytes() == original
    scaffold.apply(plan.scaffold)
    assert path.read_bytes() == original.replace(
        f'"policy_version": {before}'.encode(), f'"policy_version": {SarjPolicy.policy_version}'.encode()
    )
    assert path not in dict(service.plan_init(tmp_path).scaffold.writes)


@pytest.mark.parametrize("mutation", ["warning-ratchet", "accepted-debt", "scope"])
def test_rollout_accepts_the_empty_migration_and_rejects_other_baseline_changes(tmp_path: Path, mutation: str) -> None:
    manifest = tmp_path / ".repo-standards" / "repository.toml"
    manifest.parent.mkdir()
    manifest.write_bytes(_MANIFEST)
    path = tmp_path / repository_baseline.PATH
    original = _baseline(28).replace(b'"schema_version": 2', b'"schema_version": 2,\r\n\t"include_warnings": true')
    migrated = repository_baseline.migrate(original, _MANIFEST, target_policy_version=SarjPolicy.policy_version)
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


_ARTIFACT = (
    b'\n[[javascript.artifacts]]\npath = "eslint.strict.mjs"\nkind = "generated"\nsource = "a.toml"\nreason = "r"\n'
)


@pytest.mark.parametrize(
    ("previous", "manifest", "rescoped"),
    [
        pytest.param(_MANIFEST + _ARTIFACT, _MANIFEST, True, id="dropped-artifact"),
        pytest.param(_MANIFEST, _MANIFEST, False, id="unchanged-scope"),
    ],
)
def test_rescope_follows_a_manifest_that_only_drops_javascript_artifacts(
    previous: bytes, manifest: bytes, *, rescoped: bool
) -> None:
    original = _baseline(34, fingerprints=("f" * 64,)).replace(
        scope_digest(parse_manifest_bytes(_MANIFEST)).encode(), scope_digest(parse_manifest_bytes(previous)).encode()
    )

    result = repository_baseline.rescope(original, previous, manifest)

    expected = original.replace(
        scope_digest(parse_manifest_bytes(previous)).encode(), scope_digest(parse_manifest_bytes(manifest)).encode()
    )
    assert result == expected
    assert (result != original) is rescoped


@pytest.mark.parametrize(
    ("previous", "manifest"),
    [
        pytest.param(_MANIFEST, _MANIFEST + _ARTIFACT, id="added-artifact"),
        pytest.param(_MANIFEST + _ARTIFACT, b'repository_id = "other"\ncomponents = []\n', id="other-scope-change"),
    ],
)
def test_rescope_rejects_any_other_scope_change(previous: bytes, manifest: bytes) -> None:
    original = _baseline(34).replace(
        scope_digest(parse_manifest_bytes(_MANIFEST)).encode(), scope_digest(parse_manifest_bytes(previous)).encode()
    )

    with pytest.raises(ValueError, match="scope does not match"):
        repository_baseline.rescope(original, previous, manifest)


def test_rollout_accepts_the_rescoped_baseline_of_a_dropped_artifact(tmp_path: Path) -> None:
    manifest = tmp_path / ".repo-standards" / "repository.toml"
    manifest.parent.mkdir()
    manifest.write_bytes(_MANIFEST)
    previous = _MANIFEST + _ARTIFACT
    original = _baseline(SarjPolicy.policy_version).replace(
        scope_digest(parse_manifest_bytes(_MANIFEST)).encode(), scope_digest(parse_manifest_bytes(previous)).encode()
    )
    path = tmp_path / repository_baseline.PATH
    path.write_bytes(_baseline(SarjPolicy.policy_version))

    assert rollout.repository_baseline_migration(tmp_path, original, previous) == {path: path.read_bytes()}
    with pytest.raises(rollout.RolloutError, match="not compatible"):
        rollout.repository_baseline_migration(tmp_path, original)


@pytest.mark.parametrize(
    ("retired", "kept"),
    [
        pytest.param(("b" * 64,), ("a" * 64, "c" * 64), id="middle"),
        pytest.param(("c" * 64, "d" * 64), ("a" * 64, "b" * 64), id="last-and-unknown"),
        pytest.param(("a" * 64, "b" * 64, "c" * 64), (), id="all"),
        pytest.param((), ("a" * 64, "b" * 64, "c" * 64), id="none"),
    ],
)
def test_rescope_drops_exactly_the_retired_fingerprints(retired: tuple[str, ...], kept: tuple[str, ...]) -> None:
    original = _baseline(34, fingerprints=("a" * 64, "b" * 64, "c" * 64))

    result = repository_baseline.rescope(original, _MANIFEST, _MANIFEST, frozenset(retired))

    assert result == _baseline(34, fingerprints=kept)


def test_rollout_accepts_only_the_retired_fingerprint_removals(tmp_path: Path) -> None:
    manifest = tmp_path / ".repo-standards" / "repository.toml"
    manifest.parent.mkdir()
    manifest.write_bytes(_MANIFEST)
    previous = _MANIFEST + _ARTIFACT
    rescoped = (
        scope_digest(parse_manifest_bytes(_MANIFEST)).encode(),
        scope_digest(parse_manifest_bytes(previous)).encode(),
    )
    original = _baseline(SarjPolicy.policy_version, fingerprints=("a" * 64, "b" * 64)).replace(*rescoped)
    path = tmp_path / repository_baseline.PATH
    path.write_bytes(_baseline(SarjPolicy.policy_version, fingerprints=("a" * 64,)))

    retired = frozenset({"b" * 64})
    assert rollout.repository_baseline_migration(tmp_path, original, previous, retired) == {path: path.read_bytes()}
    with pytest.raises(rollout.RolloutError, match="fields beyond reviewed policy metadata"):
        rollout.repository_baseline_migration(tmp_path, original, previous)
    path.write_bytes(_baseline(SarjPolicy.policy_version))
    with pytest.raises(rollout.RolloutError, match="fields beyond reviewed policy metadata"):
        rollout.repository_baseline_migration(tmp_path, original, previous, retired)


def test_retired_fingerprints_name_the_committed_findings_on_deleted_files(tmp_path: Path) -> None:
    manifest = tmp_path / ".repo-standards" / "repository.toml"
    manifest.parent.mkdir()
    manifest.write_bytes(b'enabled_rules = ["repository/artifacts/untyped-javascript"]\n' + _MANIFEST)
    for name in ("eslint.config.mjs", "tool.mjs"):
        (tmp_path / name).write_text("export default [];\n", encoding="utf-8")

    baseline = tmp_path / repository_baseline.PATH
    baseline.write_bytes(_baseline(SarjPolicy.policy_version))

    assert repository_baseline.retired_fingerprints(tmp_path, {"eslint.config.mjs"}) == frozenset()
    _commit(tmp_path)
    report = analyze_repository(RepositoryAnalysisRequest(root=tmp_path))
    expected = {item.fingerprint for item in report.diagnostics if item.path == "eslint.config.mjs"}

    assert len(expected) == 1
    assert repository_baseline.retired_fingerprints(tmp_path, {"eslint.config.mjs"}) == expected
    assert repository_baseline.retired_fingerprints(tmp_path, set()) == frozenset()
    baseline.unlink()
    assert repository_baseline.retired_fingerprints(tmp_path, {"eslint.config.mjs"}) == frozenset()


def _commit(root: Path) -> None:
    identity = ("-c", "user.name=Standards Test", "-c", "user.email=standards-test@example.invalid")
    subprocess.run(("git", "init", "--quiet"), cwd=root, check=True)
    subprocess.run(("git", "add", "."), cwd=root, check=True)
    subprocess.run(
        ("git", *identity, "-c", "commit.gpgsign=false", "commit", "--quiet", "--no-verify", "-m", "fixture"),
        cwd=root,
        check=True,
    )


@pytest.mark.parametrize("version", [19, 35])
def test_current_repository_baseline_is_preserved_without_reserialization(version: int) -> None:
    original = _baseline(version, fingerprints=("b" * 64,))

    assert repository_baseline.migrate(original, _MANIFEST, target_policy_version=version) == original


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


@pytest.mark.parametrize(("before", "target"), [(18, 19), (34, 35)])
@pytest.mark.parametrize("invalid", ["repository", "policy", "scope", "schema", "duplicate-key", "unsupported-version"])
def test_unreviewed_or_mismatched_repository_baselines_cannot_migrate(before: int, target: int, invalid: str) -> None:
    original = _baseline(before)
    replacements = {
        "repository": (b'"fixture"', b'"other"'),
        "policy": (b'"sarj"', b'"other"'),
        "scope": (scope_digest(parse_manifest_bytes(_MANIFEST)).encode(), b"0" * 64),
        "schema": (b'"schema_version": 2', b'"schema_version": 1'),
        "duplicate-key": (
            f'"policy_version": {before}'.encode(),
            f'"policy_version": {before}, "policy_version": {before}'.encode(),
        ),
        "unsupported-version": (f'"policy_version": {before}'.encode(), b'"policy_version": 17'),
    }
    previous_value, replacement = replacements[invalid]

    with pytest.raises(ValueError, match=r"baseline|duplicate JSON key"):
        repository_baseline.migrate(
            original.replace(previous_value, replacement), _MANIFEST, target_policy_version=target
        )


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


@pytest.mark.parametrize("before", [32, 33], ids=["composed-policy32", "policy33"])
@pytest.mark.parametrize("target", [34, 35])
@pytest.mark.parametrize("include_warnings", [None, False, True], ids=["legacy", "errors", "warnings"])
@pytest.mark.parametrize(
    "manifest",
    [pytest.param(_MANIFEST, id="no-pull-request"), pytest.param(_COMMIT_ONLY_MANIFEST, id="no-review-policy")],
)
def test_template_policy_preserves_nonempty_debt_when_template_review_cannot_run(
    before: int, target: int, include_warnings: bool | None, manifest: bytes
) -> None:
    original = _baseline(before, fingerprints=("a" * 64, "f" * 64))
    if include_warnings is not None:
        original = original.replace(
            b'"schema_version": 2',
            b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
        )

    migrated = repository_baseline.migrate(original, manifest, target_policy_version=target)

    assert migrated == original.replace(f'"policy_version": {before}'.encode(), f'"policy_version": {target}'.encode())
    assert json.loads(migrated)["fingerprints"] == ["a" * 64, "f" * 64]


@pytest.mark.parametrize(("before", "target"), [(33, 34), (34, 35), (33, 35)])
@pytest.mark.parametrize("include_warnings", [None, False, True], ids=["legacy", "errors", "warnings"])
@pytest.mark.parametrize("required_sections", [True, False], ids=["required-heading", "empty-headings"])
def test_template_policy_requires_separate_review_for_nonempty_template_scope_debt(
    before: int, target: int, include_warnings: bool | None, *, required_sections: bool
) -> None:
    manifest = _REVIEW_MANIFEST if required_sections else _REVIEW_MANIFEST.replace(b'["Test evidence"]', b"[]")
    original = _baseline(before, fingerprints=("b" * 64,))
    if include_warnings is not None:
        original = original.replace(
            b'"schema_version": 2',
            b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
        )
    assert scope_digest(parse_manifest_bytes(manifest)) == scope_digest(parse_manifest_bytes(_MANIFEST))

    with pytest.raises(ValueError, match="requires a separately reviewed compatibility decision"):
        repository_baseline.migrate(original, manifest, target_policy_version=target)


@pytest.mark.parametrize(("before", "target"), [(33, 34), (34, 35), (33, 35), (32, 35)])
@pytest.mark.parametrize("include_warnings", [None, False, True], ids=["legacy", "errors", "warnings"])
@pytest.mark.parametrize("required_sections", [True, False], ids=["required-heading", "empty-headings"])
def test_template_policy_can_migrate_an_empty_scope_without_accepting_new_debt(
    before: int, target: int, include_warnings: bool | None, *, required_sections: bool
) -> None:
    manifest = _REVIEW_MANIFEST if required_sections else _REVIEW_MANIFEST.replace(b'["Test evidence"]', b"[]")
    original = _baseline(before)
    if include_warnings is not None:
        original = original.replace(
            b'"schema_version": 2',
            b'"schema_version": 2,\r\n\t"include_warnings": ' + str(include_warnings).lower().encode("ascii"),
        )

    migrated = repository_baseline.migrate(original, manifest, target_policy_version=target)

    assert migrated == original.replace(f'"policy_version": {before}'.encode(), f'"policy_version": {target}'.encode())
    assert json.loads(migrated)["fingerprints"] == []


@pytest.mark.parametrize(
    "before", [27, 29, 31], ids=["operational-debt", "migration-warning-debt", "image-warning-debt"]
)
@pytest.mark.parametrize("target", [34, 35])
def test_template_policy_composition_preserves_prior_nonempty_warning_debt_rejections(before: int, target: int) -> None:
    original = _baseline(before, fingerprints=("b" * 64,)).replace(
        b'"schema_version": 2', b'"schema_version": 2,\r\n\t"include_warnings": true'
    )

    with pytest.raises(ValueError, match="requires a separately reviewed compatibility decision"):
        repository_baseline.migrate(original, _MANIFEST, target_policy_version=target)
