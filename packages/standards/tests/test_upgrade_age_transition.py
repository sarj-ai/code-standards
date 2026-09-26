from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import age_transition, lifecycle, manifest, transaction, upgrade
from sarj_standards.libs.yaml_boundary import parse_yaml


if TYPE_CHECKING:
    from collections.abc import Sequence


OLD = "@sarj/eslint-plugin@15.27.0"


@dataclass
class Fixture:
    plan: upgrade.UpgradePlan
    policy: Path
    original: str


def _plan(root: Path) -> Fixture:
    (root / manifest.MANIFEST_NAME).write_text(
        manifest.Manifest(version="0.0.1", configs=(), python_dest=".", typescript_dest=".").render()
    )
    policy = root / "pnpm-workspace.yaml"
    original = (
        "minimumReleaseAge: 1440\nminimumReleaseAgeStrict: true\n"
        f'minimumReleaseAgeExclude:\n  - "{OLD}"\n  - "third-party@1.0.0" # retained\n'
        "ignoreScripts: true\n"
    )
    policy.write_text(original)
    return Fixture(upgrade.build_plan(root), policy, original)


def _approvals(policy: Path) -> list[str]:
    parsed = parse_yaml(policy.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    values: object = parsed["minimumReleaseAgeExclude"]  # pyright: ignore[reportUnknownVariableType] -- narrowed YAML fixture boundary.
    assert isinstance(values, list)
    items: list[object] = values  # pyright: ignore[reportUnknownVariableType] -- narrowed YAML sequence boundary.
    return [value for value in items if isinstance(value, str)]


def test_install_retains_existing_exact_approval_then_restores_canonical_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _plan(tmp_path)
    plan, policy = fixture.plan, fixture.policy
    target = f"@sarj/eslint-plugin@{manifest.eslint_age_gate_preapprovals()['@sarj/eslint-plugin']}"
    canonical = dict(plan.pin_writes)[policy]
    seen: list[object] = []

    def execute(_commands: Sequence[lifecycle.Command]) -> int:
        approvals = _approvals(policy)
        seen.append(approvals)
        return 0 if OLD in approvals else 1

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- installer interception tests upgrade transaction boundaries without executing consumer code.
        lifecycle, "execute", execute
    )
    assert upgrade.apply(plan) == 0
    assert seen == [[OLD, "third-party@1.0.0", target]]
    assert policy.read_text(encoding="utf-8") == canonical
    assert OLD not in _approvals(policy)


@pytest.mark.parametrize("status", [1, 130])
def test_failed_install_rolls_back_temporary_approvals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    fixture = _plan(tmp_path)
    plan, policy, original = fixture.plan, fixture.policy, fixture.original
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}

    def execute(_commands: Sequence[lifecycle.Command]) -> int:
        assert OLD in _approvals(policy)
        if status == 130:
            raise KeyboardInterrupt
        return status

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- installer interception tests upgrade transaction boundaries without executing consumer code.
        lifecycle, "execute", execute
    )
    assert upgrade.apply(plan) == status
    assert policy.read_text(encoding="utf-8") == original
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_concurrent_policy_edit_survives_failed_restoration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _plan(tmp_path)
    plan, policy = fixture.plan, fixture.policy
    concurrent = "minimumReleaseAge: 99999\n"

    def execute(_commands: Sequence[lifecycle.Command]) -> int:
        policy.write_text(concurrent)
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- installer interception tests upgrade transaction boundaries without executing consumer code.
        lifecycle, "execute", execute
    )
    with pytest.raises(OSError, match="recovery incomplete"):
        upgrade.apply(plan)
    assert policy.read_text(encoding="utf-8") == concurrent


def test_no_install_does_not_retain_previous_approvals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _plan(tmp_path)
    plan, policy = fixture.plan, fixture.policy

    def execute(_commands: Sequence[lifecycle.Command]) -> int:
        pytest.fail("no-install must not invoke an installer")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- installer interception tests upgrade transaction boundaries without executing consumer code.
        lifecycle, "execute", execute
    )
    assert upgrade.apply(plan, install=False) == 0
    assert policy.read_text(encoding="utf-8") == dict(plan.pin_writes)[policy]


@pytest.mark.parametrize("flow", [False, True])
def test_transition_only_retains_previously_approved_exact_owned_versions(tmp_path: Path, flow: bool) -> None:
    policy = tmp_path / "pnpm-workspace.yaml"
    old = (
        f'minimumReleaseAgeExclude: ["{OLD}", "@sarj/eslint-plugin@*", '
        '"@sarj/eslint-plugin@^15.0.0", "@typescript-eslint/parser@8.70.1", "unrelated@1.0.0"]\n'
    )
    target = f"@sarj/eslint-plugin@{manifest.eslint_age_gate_preapprovals()['@sarj/eslint-plugin']}"
    canonical = (
        f'minimumReleaseAgeExclude: ["{target}", "unrelated@2.0.0"] # keep\n'
        if flow
        else f'minimumReleaseAgeExclude:\n  - "{target}" # keep\n  - "unrelated@2.0.0"\n'
    ) + "minimumReleaseAge: 20160\n"
    policy.write_text(old)
    files = transaction.FileTransaction.capture(tmp_path, (policy,))
    files.write_text(policy, canonical)

    assert age_transition.retain_previous_approvals(files, {policy: old.encode()}) == ((policy, canonical),)
    assert _approvals(policy) == [OLD, target, "unrelated@2.0.0"]
    assert "# keep\n" in policy.read_text(encoding="utf-8")
    assert "minimumReleaseAge: 20160\n" in policy.read_text(encoding="utf-8")
    files.write_text(policy, canonical)
    assert policy.read_text(encoding="utf-8") == canonical


def test_transition_never_writes_an_unplanned_policy(tmp_path: Path) -> None:
    policy = tmp_path / "pnpm-workspace.yaml"
    original = f'minimumReleaseAgeExclude: ["{OLD}"]\n'
    policy.write_text(original)
    files = transaction.FileTransaction.capture(tmp_path, (policy,))
    assert age_transition.retain_previous_approvals(files, {policy: original.encode()}) == ()
    assert policy.read_text(encoding="utf-8") == original


def test_transition_rejects_anchored_policy_without_modifying_aliases(tmp_path: Path) -> None:
    policy = tmp_path / "pnpm-workspace.yaml"
    original = f'minimumReleaseAgeExclude: ["{OLD}"]\n'
    target = f"@sarj/eslint-plugin@{manifest.eslint_age_gate_preapprovals()['@sarj/eslint-plugin']}"
    canonical = f'minimumReleaseAgeExclude: &approved ["{target}"]\nother: *approved\n'
    policy.write_text(original)
    files = transaction.FileTransaction.capture(tmp_path, (policy,))
    files.write_text(policy, canonical)
    with pytest.raises(ValueError, match="anchored"):
        age_transition.retain_previous_approvals(files, {policy: original.encode()})
    assert policy.read_text(encoding="utf-8") == canonical
