from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import doctor, manifest, scaffold
from sarj_standards.libs.release import rollout


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("typescript_dest", [".", "frontend"], ids=["root", "adopted-typescript-directory"])
@pytest.mark.parametrize(
    ("filename", "unchanged_settings", "old_exclusions"),
    [
        (
            ".npmrc",
            "min-release-age=20160\nstrict-ssl=true\nregistry=https://registry.npmjs.org/\n",
            "min-release-age-exclude=unrelated,external-parser\n",
        ),
        (
            ".yarnrc.yaml",
            "npmMinimalAgeGate: 20160\nenableScripts: false\n",
            'npmPreapprovedPackages:\n  - "unrelated@1.2.3" # retained\n  - "external-parser@8.67.0"\n',
        ),
    ],
    ids=["npm", "yarn-yaml"],
)
def test_rollout_dependency_update_preserves_consumer_age_policy(
    tmp_path: Path,
    *,
    typescript_dest: str,
    filename: str,
    unchanged_settings: str,
    old_exclusions: str,
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
    package = project / "package.json"
    package.write_text('{"devDependencies":{"@sarj/oxlint-plugin":"15.9.0"}}\n', encoding="utf-8")
    allowed = rollout.managed_rollout_paths(tmp_path, frozenset())

    versions = {"@sarj/oxlint-plugin": manifest.oxlint_peers()["@sarj/oxlint-plugin"]}
    [update] = doctor.plan_version_pin_updates(tmp_path, versions)

    assert update.path == package
    assert versions["@sarj/oxlint-plugin"] in update.contents
    assert policy.read_text(encoding="utf-8") == unchanged_settings + old_exclusions
    rollout.reject_unsafe_diff((update.path.relative_to(tmp_path).as_posix(),), allowed_paths=allowed)
    update.path.write_text(update.contents, encoding="utf-8")
    assert doctor.plan_version_pin_updates(tmp_path, versions) == ()
    assert policy.read_text(encoding="utf-8") == unchanged_settings + old_exclusions
    assert unrelated.read_text(encoding="utf-8") == "registry=https://registry.example.test/\n"
    for protected in (
        unrelated.relative_to(tmp_path).as_posix(),
        f"scripts/{filename}",
        "src/app.py",
        "src/settings.ini",
    ):
        with pytest.raises(rollout.RolloutError, match="protected paths"):
            rollout.reject_unsafe_diff((protected,), allowed_paths=allowed)


def test_actual_adoption_formatter_plan_is_allowed_without_allowing_application_source(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"consumer","private":true,"packageManager":"npm@12.1.0"}')
    plan = scaffold.build_plan(tmp_path, force=False, configs=("oxlint",), hook_manager="none")
    assert not plan.errors
    formatter = next(path for path, _contents in plan.writes if path.name == ".oxfmtrc.json")
    allowed = rollout.managed_rollout_paths(tmp_path, frozenset())
    rollout.reject_unsafe_diff((formatter.relative_to(tmp_path).as_posix(),), allowed_paths=allowed)
    with pytest.raises(rollout.RolloutError, match="protected paths"):
        rollout.reject_unsafe_diff(("src/app.ts",), allowed_paths=allowed)


def test_rollout_preserves_supported_authored_native_config_variants(tmp_path: Path) -> None:
    config = tmp_path / "oxlint.config.mts"
    config.write_text("export default {};\n")
    allowed = rollout.managed_rollout_paths(tmp_path, frozenset())
    rollout.reject_unsafe_diff((config.name,), allowed_paths=allowed)
