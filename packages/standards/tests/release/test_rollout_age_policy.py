from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import doctor, manifest
from sarj_standards.libs.release import rollout


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("typescript_dest", [".", "frontend"], ids=["root", "adopted-typescript-directory"])
@pytest.mark.parametrize(
    ("filename", "unchanged_settings", "old_exclusions", "new_exclusions"),
    [
        (
            ".npmrc",
            "min-release-age=20160\nstrict-ssl=true\nregistry=https://registry.npmjs.org/\n",
            "min-release-age-exclude=unrelated,@sarj/eslint-plugin,@typescript-eslint/parser\n",
            "min-release-age-exclude=unrelated,@sarj/eslint-plugin\n",
        ),
        (
            ".yarnrc.yaml",
            "npmMinimalAgeGate: 20160\nenableScripts: false\n",
            'npmPreapprovedPackages:\n  - "unrelated@1.2.3" # retained\n  - "@typescript-eslint/parser@8.67.0"\n',
            (
                'npmPreapprovedPackages:\n  - "unrelated@1.2.3" # retained\n'
                f'  - "@sarj/eslint-plugin@{manifest.eslint_peers()["@sarj/eslint-plugin"]}"\n'
            ),
        ),
    ],
    ids=["npm", "yarn-yaml"],
)
def test_rollout_accepts_adoption_age_policy_rewrite(
    tmp_path: Path,
    *,
    typescript_dest: str,
    filename: str,
    unchanged_settings: str,
    old_exclusions: str,
    new_exclusions: str,
) -> None:
    (tmp_path / rollout.MANIFEST).write_text(
        f'schema = 4\nbundle = "8.1.3"\n[dest]\ntypescript = "{typescript_dest}"\n',
        encoding="utf-8",
    )
    project = tmp_path / typescript_dest
    project.mkdir(exist_ok=True)
    policy = project / filename
    policy.write_text(unchanged_settings + old_exclusions, encoding="utf-8")
    unrelated = project / f"{filename}.local"
    unrelated.write_text("registry=https://registry.example.test/\n", encoding="utf-8")
    allowed = rollout.managed_rollout_paths(tmp_path, frozenset())

    [update] = doctor.plan_version_pin_updates(tmp_path)

    assert update.path == policy
    assert update.contents == unchanged_settings + new_exclusions
    rollout.reject_unsafe_diff((update.path.relative_to(tmp_path).as_posix(),), allowed_paths=allowed)
    update.path.write_text(update.contents, encoding="utf-8")
    assert doctor.plan_version_pin_updates(tmp_path) == ()
    assert unrelated.read_text(encoding="utf-8") == "registry=https://registry.example.test/\n"
    for protected in (
        unrelated.relative_to(tmp_path).as_posix(),
        f"scripts/{filename}",
        "src/app.py",
        "src/settings.ini",
    ):
        with pytest.raises(rollout.RolloutError, match="protected paths"):
            rollout.reject_unsafe_diff((protected,), allowed_paths=allowed)
