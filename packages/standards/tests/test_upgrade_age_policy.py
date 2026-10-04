from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import lifecycle, manifest, upgrade


if TYPE_CHECKING:
    from collections.abc import Sequence


OLD = "@sarj/oxlint-plugin@15.27.0"


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


def test_install_preserves_authored_age_policy_throughout_the_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _plan(tmp_path)
    seen: list[str] = []

    def execute(_commands: Sequence[lifecycle.Command]) -> int:
        seen.append(fixture.policy.read_text(encoding="utf-8"))
        return 0

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- installer interception tests upgrade transaction boundaries without executing consumer code.
        lifecycle, "execute", execute
    )
    assert upgrade.apply(fixture.plan) == 0
    assert seen == [fixture.original]
    assert fixture.policy.read_text(encoding="utf-8") == fixture.original


@pytest.mark.parametrize("status", [1, 130])
def test_failed_install_preserves_age_policy_and_rolls_back_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    fixture = _plan(tmp_path)
    plan, policy, original = fixture.plan, fixture.policy, fixture.original
    before = {path: path.read_bytes() for path in tmp_path.iterdir()}

    def execute(_commands: Sequence[lifecycle.Command]) -> int:
        assert policy.read_text(encoding="utf-8") == original
        if status == 130:
            raise KeyboardInterrupt
        return status

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- installer interception tests upgrade transaction boundaries without executing consumer code.
        lifecycle, "execute", execute
    )
    assert upgrade.apply(plan) == status
    assert policy.read_text(encoding="utf-8") == original
    assert {path: path.read_bytes() for path in tmp_path.iterdir()} == before


def test_no_install_preserves_age_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _plan(tmp_path)
    plan, policy = fixture.plan, fixture.policy

    def execute(_commands: Sequence[lifecycle.Command]) -> int:
        pytest.fail("no-install must not invoke an installer")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- installer interception tests upgrade transaction boundaries without executing consumer code.
        lifecycle, "execute", execute
    )
    assert upgrade.apply(plan, install=False) == 0
    assert policy.read_text(encoding="utf-8") == fixture.original
