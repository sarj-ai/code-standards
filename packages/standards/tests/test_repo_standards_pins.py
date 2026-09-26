from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml

from sarj_standards.libs.adoption import doctor, manifest, scaffold, upgrade


if TYPE_CHECKING:
    from pathlib import Path


_REVISION = "2e44cf52cb569e8f5dcdc7b00de2f7a4b6b50310"


def test_repo_standards_dependency_pin_tracks_the_installed_package() -> None:
    result = doctor.rewrite_version_pins('dependencies = ["repo-standards>=6.0.1"]\n', {"repo-standards": "6.1.0"})

    assert result.contents == 'dependencies = ["repo-standards==6.1.0"]\n'
    assert result.packages == ("repo-standards",)
    assert "repo-standards" in manifest.installed_versions()


def test_repo_standards_pin_does_not_match_another_package_suffix() -> None:
    original = 'dependencies = ["other-repo-standards==1.0", "other_repo-standards==1.0"]\n'

    assert doctor.rewrite_version_pins(original, {"repo-standards": "6.1.0"}).contents == original


@pytest.mark.parametrize("action", ["", "/documentation", "/pull-request-commits", "/pull-request-review-policy"])
@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_existing_workflow_actions_preserve_options_and_quotes(tmp_path: Path, action: str, quote: str) -> None:
    workflow = tmp_path / ".github" / "workflows" / "policy.yml"
    workflow.parent.mkdir(parents=True)
    original = (
        "jobs:\n  policy:\n    steps:\n"
        f"      - uses: {quote}sarj-ai/repo-standards{action}@v6.0.1{quote} # v6.0.1\n"
        "        with:\n          strict: false\n"
    )
    workflow.write_text(original, encoding="utf-8")

    [update] = doctor.plan_version_pin_updates(tmp_path, {"repo-standards": "6.1.0"})

    expected = original.replace("@v6.0.1", f"@{_REVISION}").replace("# v6.0.1", "# v6.1.0")
    assert update.contents == expected
    assert update.packages == ("repo-standards",)
    workflow.write_text(update.contents, encoding="utf-8")
    assert not doctor.plan_version_pin_updates(tmp_path, {"repo-standards": "6.1.0"})


def test_action_update_ignores_shell_text_comments_and_unrelated_uses(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "policy.yml"
    workflow.parent.mkdir(parents=True)
    original = (
        "# uses: sarj-ai/repo-standards@v6.0.1\n"
        "env:\n  uses: sarj-ai/repo-standards@v6.0.1\n"
        "jobs:\n  policy:\n    steps:\n"
        "      - run: |\n          cat <<'YAML'\n          uses: sarj-ai/repo-standards@v6.0.1\n          YAML\n"
        "      - uses: other/repo-standards@v6.0.1\n"
        "      - uses: sarj-ai/repo-standards/unknown@v6.0.1\n"
        "      - uses: sarj-ai/repo-standards@${{ inputs.ref }}\n"
        "      - uses: sarj-ai/repo-standards@v6.0.1 # reviewed exception; keep this explanation\n"
    )
    workflow.write_text(original, encoding="utf-8")

    [update] = doctor.plan_version_pin_updates(tmp_path, {"repo-standards": "6.1.0"})

    assert update.contents == original.replace(
        "sarj-ai/repo-standards@v6.0.1 # reviewed", f"sarj-ai/repo-standards@{_REVISION} # reviewed"
    )


def test_action_update_respects_doctor_exclusions_and_workflow_boundary(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "policy.yml"
    workflow.parent.mkdir(parents=True)
    text = "jobs:\n  policy:\n    steps:\n      - uses: sarj-ai/repo-standards@v6.0.1\n"
    workflow.write_text(text, encoding="utf-8")
    (tmp_path / "lefthook.yml").write_text(text, encoding="utf-8")
    (tmp_path / manifest.MANIFEST_NAME).write_text(
        '[doctor]\nexclude = [".github/workflows/policy.yml"]\n', encoding="utf-8"
    )

    assert not doctor.plan_version_pin_updates(tmp_path, {"repo-standards": "6.1.0"})


def test_generated_commit_policy_uses_the_published_repo_standards_identity() -> None:
    assert manifest.installed_versions()["repo-standards"] == manifest.REPO_STANDARDS_VERSION
    assert (
        f"sarj-ai/repo-standards/pull-request-commits@{_REVISION} # v6.1.0" in scaffold.commit_policy_github_workflow()
    )


@pytest.mark.parametrize("excluded", [False, True])
def test_upgrade_composes_action_pins_with_a_legacy_workflow_migration(tmp_path: Path, *, excluded: bool) -> None:
    adopted = manifest.Manifest(
        version="0.0.1",
        configs=(),
        python_dest=".",
        typescript_dest=".",
        doctor_excluded_paths=(".github/workflows/*.yml",) if excluded else (),
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    workflow = tmp_path / ".github" / "workflows" / "standards.yml"
    workflow.parent.mkdir(parents=True)
    original = (
        "name: Custom checks\non: push\njobs:\n  check:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: sarj-ai/repo-standards@v6.0.1 # v6.0.1\n"
        "        with:\n          strict: false\n"
        "      - run: uv run sarj-standards verify\n"
    )
    workflow.write_text(original, encoding="utf-8")

    assert upgrade.apply(upgrade.build_plan(tmp_path), install=False) == 0

    expected = original.replace(" verify", " check --trust-repository-code")
    if not excluded:
        expected = expected.replace("@v6.0.1", f"@{_REVISION}").replace("# v6.0.1", "# v6.1.0")
    assert workflow.read_text(encoding="utf-8") == expected
    assert workflow not in {update.path for update in doctor.plan_version_pin_updates(tmp_path)}
    assert upgrade.apply(upgrade.build_plan(tmp_path), install=False) == 0
    assert workflow.read_text(encoding="utf-8") == expected


@pytest.mark.parametrize(
    "source",
    [
        "env:\n  action: &action sarj-ai/repo-standards@v6.0.1\njobs:\n  policy:\n    steps:\n      - uses: *action\n",
        "env:\n  step: &step\n    uses: sarj-ai/repo-standards@v6.0.1\njobs:\n  policy:\n    steps: [*step]\n",
        "env:\n  template: &job {steps: [{uses: sarj-ai/repo-standards@v6.0.1}]}\njobs:\n  policy: *job\n",
        "env:\n  template: &jobs {policy: {steps: [{uses: sarj-ai/repo-standards@v6.0.1}]}}\njobs: *jobs\n",
        "jobs:\n  policy:\n    steps:\n      - uses: &action sarj-ai/repo-standards@v6.0.1\n      - uses: *action\n",
        "jobs:\n  policy:\n    steps:\n      - uses: !custom sarj-ai/repo-standards@v6.0.1\n",
        'jobs:\n  policy:\n    steps:\n      - uses: "sarj-ai/repo-standards@v6\\x2e0.1"\n',
        "jobs:\n  policy:\n    steps:\n      - uses: sarj-ai/repo-standards@v6.0.1\n        uses: other/action@v1\n",
        "jobs: [invalid YAML\n",
    ],
)
def test_action_update_preserves_ambiguous_or_indirect_yaml(tmp_path: Path, source: str) -> None:
    workflow = tmp_path / ".github" / "workflows" / "policy.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(source, encoding="utf-8")

    assert not doctor.plan_version_pin_updates(tmp_path, {"repo-standards": "6.1.0"})


def test_action_update_preserves_valid_anchor_references_when_updating_another_step(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "policy.yml"
    workflow.parent.mkdir(parents=True)
    original = (
        "jobs:\n  policy:\n    steps:\n"
        "      - uses: &action sarj-ai/repo-standards@v6.0.1\n"
        "      - uses: *action\n"
        "      - uses: sarj-ai/repo-standards/documentation@v6.0.1\n"
    )
    workflow.write_text(original, encoding="utf-8")

    [update] = doctor.plan_version_pin_updates(tmp_path, {"repo-standards": "6.1.0"})

    expected = original.replace("/documentation@v6.0.1", f"/documentation@{_REVISION}")
    assert update.contents == expected
    assert yaml.compose(update.contents, Loader=yaml.SafeLoader) is not None  # pyright: ignore[reportUnknownMemberType] -- Verify actual YAML parsing preserves valid aliases.
