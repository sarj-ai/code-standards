"""A standards upgrade is previewable, coherent, and rollback-safe."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs import __main__ as cli
from sarj_lint_configs import doctor, manifest, upgrade


if TYPE_CHECKING:
    from pathlib import Path


def _outdated_python_repo(root: Path) -> Path:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\n\n[tool.ruff]\nextend = ".ruff-strict.toml"\n',
        encoding="utf-8",
    )
    (root / "pyrightconfig.json").write_text('{"extends": ".pyright-strict.json"}\n', encoding="utf-8")
    adopted = manifest.Manifest(
        version="0.0.1",
        configs=("ruff", "pyright", "markdownlint", "taplo", "yamllint"),
        python_dest=".",
        typescript_dest=".",
    )
    text = f"{adopted.render()}\n[consumer]\nkeep = true\n"
    (root / manifest.MANIFEST_NAME).write_text(text, encoding="utf-8")
    for name in (".ruff-strict.toml", ".pyright-strict.json", ".markdownlint.yaml", ".taplo.toml", ".yamllint.yaml"):
        (root / name).write_text("stale\n", encoding="utf-8")
    return root


def test_upgrade_preview_is_read_only_and_names_every_change(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}

    plan = upgrade.build_plan(tmp_path)

    assert "sync ruff config" in upgrade.render(plan.changes)
    assert "adopt lint-configs" in upgrade.render(plan.changes)
    assert {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()} == before


def test_upgrade_repairs_the_bundle_without_losing_manifest_extensions(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)

    status = upgrade.apply(upgrade.build_plan(tmp_path), install=False)

    assert status == 0
    manifest_text = (tmp_path / manifest.MANIFEST_NAME).read_text(encoding="utf-8")
    assert f'version = "{manifest.adopted_version()}"' in manifest_text
    assert "[consumer]\nkeep = true" in manifest_text
    assert not [finding for finding in doctor.diagnose(tmp_path) if finding.level is doctor.Level.DRIFT]


def test_upgrade_no_install_skips_dependency_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    install_values: list[bool] = []

    def apply_without_side_effects(_plan: upgrade.UpgradePlan, *, install: bool = True) -> int:
        install_values.append(install)
        return 0

    monkeypatch.setattr(upgrade, "apply", apply_without_side_effects)

    assert cli.main(["upgrade", "--offline", "--no-install", "--dest", str(tmp_path)]) == 0
    assert install_values == [False]


def test_upgrade_rolls_back_every_touched_file_when_postflight_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _outdated_python_repo(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}

    def drift(_root: Path) -> list[doctor.Finding]:
        return [doctor.Finding(doctor.Level.DRIFT, "test", "forced postflight failure")]

    monkeypatch.setattr(doctor, "diagnose", drift)
    assert upgrade.apply(upgrade.build_plan(tmp_path), install=False) == 1
    assert {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()} == before


def test_upgrade_rejects_a_manifest_destination_outside_the_repo(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    adopted = manifest.Manifest(
        version="0.0.1",
        configs=("ruff",),
        python_dest="../outside",
        typescript_dest=".",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    with pytest.raises(ValueError, match="escapes repository root"):
        upgrade.build_plan(tmp_path)


def test_upgrade_does_not_block_on_retired_ids_in_a_config_it_will_replace(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    (tmp_path / ".ruff-strict.toml").write_text(
        "# sarj-noqa: SARJ061\n",
        encoding="utf-8",
    )

    plan = upgrade.build_plan(tmp_path)

    assert upgrade.unsafe_retired_findings(plan) == []


def test_upgrade_respects_explicit_doctor_fixture_exclusions(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    fixture = tmp_path / "tests" / "retired_fixture.py"
    fixture.parent.mkdir()
    fixture.write_text("# sarj-noqa: SARJ061\n", encoding="utf-8")
    manifest_path = tmp_path / manifest.MANIFEST_NAME
    manifest_path.write_text(
        f'{manifest_path.read_text(encoding="utf-8")}\n[doctor]\nexclude = ["tests/retired_fixture.py"]\n',
        encoding="utf-8",
    )

    assert upgrade.unsafe_retired_findings(upgrade.build_plan(tmp_path)) == []


def test_upgrade_rejects_a_symlinked_manifest_without_touching_its_target(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    manifest_path = tmp_path / manifest.MANIFEST_NAME
    outside = tmp_path.parent / f"{tmp_path.name}-manifest.toml"
    outside.write_bytes(manifest_path.read_bytes())
    manifest_path.unlink()
    manifest_path.symlink_to(outside)
    before = outside.read_bytes()

    assert upgrade.apply(upgrade.build_plan(tmp_path), install=False) == 2
    assert outside.read_bytes() == before


def test_upgrade_rolls_back_new_lockfile_and_interrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _outdated_python_repo(tmp_path)

    def interrupted(_commands: object) -> int:
        (tmp_path / "uv.lock").write_text("partial\n", encoding="utf-8")
        raise KeyboardInterrupt

    monkeypatch.setattr(upgrade.lifecycle, "execute", interrupted)

    assert upgrade.apply(upgrade.build_plan(tmp_path)) == 130
    assert not (tmp_path / "uv.lock").exists()


def test_upgrade_refreshes_every_doctor_owned_pin_site_without_thrashing(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    lint_configs = manifest.installed_versions()["sarj-lint-configs"]
    python_lint = manifest.installed_versions()["sarj-python-lint"]
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            '[project]\nname = "app"\nversion = "0.1.0"',
            '[project]\nname = "app"\nversion = "0.1.0"\ndependencies = ["sarj-python-lint==0.1.0"]',
        ),
        encoding="utf-8",
    )
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        "      - id: sarj-standards-drift\n"
        "        entry: uvx --from sarj-lint-configs==0.1.0 sarj-standards doctor\n"
        "        language: system\n"
        "        pass_filenames: false\n"
        "      - id: sarj-standards-check\n"
        "        entry: uvx --from sarj-lint-configs==0.1.0 sarj-standards check\n"
        "        language: system\n",
        encoding="utf-8",
    )
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "standards.yml").write_text(
        "jobs:\n  lint:\n    steps:\n      - run: uvx --from sarj-lint-configs==0.1.0 sarj-standards verify\n",
        encoding="utf-8",
    )
    (tmp_path / "requirements-dev.txt").write_text("sarj-python-lint>=0.1.0\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        '{"scripts":{"lint":"uvx --from sarj-lint-configs==0.1.0 sarj-standards check ."}}\n',
        encoding="utf-8",
    )

    plan = upgrade.build_plan(tmp_path)

    assert "refresh sarj-lint-configs version pin" in upgrade.render(plan.changes)
    assert upgrade.apply(plan, install=False) == 0
    precommit = (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    workflow = (workflows / "standards.yml").read_text(encoding="utf-8")
    package_json = (tmp_path / "package.json").read_text(encoding="utf-8")
    assert f"sarj-lint-configs=={lint_configs}" in precommit
    assert f"sarj-lint-configs=={lint_configs}" in workflow
    assert f"sarj-lint-configs=={lint_configs}" in package_json
    assert "verbose: true" in (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert f"sarj-python-lint=={python_lint}" in pyproject.read_text(encoding="utf-8")
    assert f"sarj-python-lint>={python_lint}" in (tmp_path / "requirements-dev.txt").read_text(encoding="utf-8")
    assert not [finding for finding in doctor.diagnose(tmp_path) if finding.level is doctor.Level.DRIFT]


def test_upgrade_rolls_back_a_migrated_workflow_pin_on_postflight_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _outdated_python_repo(tmp_path)
    workflow = tmp_path / ".github" / "workflows" / "standards.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  lint:\n    steps:\n      - run: uvx --from sarj-lint-configs==0.1.0 sarj-standards verify\n",
        encoding="utf-8",
    )
    before = workflow.read_bytes()
    plan = upgrade.build_plan(tmp_path)

    def drift(_root: Path) -> list[doctor.Finding]:
        return [doctor.Finding(doctor.Level.DRIFT, "test", "forced postflight failure")]

    monkeypatch.setattr(doctor, "diagnose", drift)

    assert upgrade.apply(plan, install=False) == 1
    assert workflow.read_bytes() == before
