"""A standards upgrade is previewable, coherent, and rollback-safe."""

# sarj-doctor-ignore-retired-rules -- upgrade fixtures intentionally contain
# retired identifiers so migration behavior remains covered.

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
import yaml

from sarj_lint_configs import __main__ as cli
from sarj_lint_configs import doctor, manifest, upgrade
from sarj_lint_configs.libs.adoption import transaction


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


def test_upgrade_plan_normalizes_a_repository_alias(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _outdated_python_repo(repository)
    alias = tmp_path / "alias"
    alias.symlink_to(repository, target_is_directory=True)

    plan = upgrade.build_plan(alias)

    assert plan.root == repository.resolve()


@pytest.mark.parametrize("suffix", ["+corp", "_rc1"])
def test_pin_rewrite_does_not_accept_a_version_suffix_as_the_installed_release(suffix: str) -> None:
    current = manifest.installed_versions()["sarj-lint-configs"]
    text = f"sarj-lint-configs=={current}{suffix}\n"

    rewritten = doctor.rewrite_version_pins(text, {"sarj-lint-configs": current})

    assert rewritten.contents == f"sarj-lint-configs=={current}\n"
    assert rewritten.packages == ("sarj-lint-configs",)


def test_upgrade_rejects_a_manifest_newer_than_the_executing_bundle_without_writes(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    path = tmp_path / manifest.MANIFEST_NAME
    path.write_text(path.read_text().replace('version = "0.0.1"', 'version = "9999.0"'))
    before = {candidate: candidate.read_bytes() for candidate in tmp_path.iterdir() if candidate.is_file()}

    with pytest.raises(ValueError, match=r"newer standards 9999\.0"):
        upgrade.build_plan(tmp_path)
    assert {candidate: candidate.read_bytes() for candidate in tmp_path.iterdir() if candidate.is_file()} == before


def test_upgrade_apply_rejects_a_forged_newer_plan_without_writes(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    plan = upgrade.build_plan(tmp_path)
    newer = replace(plan, adopted=replace(plan.adopted, version="9999.0"))
    before = {candidate: candidate.read_bytes() for candidate in tmp_path.iterdir() if candidate.is_file()}

    assert upgrade.apply(newer, install=False) == 2
    assert {candidate: candidate.read_bytes() for candidate in tmp_path.iterdir() if candidate.is_file()} == before


def test_upgrade_installs_only_ecosystems_adopted_by_the_manifest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0.1.0"\n')
    (tmp_path / "package.json").write_text('{"name":"web","private":true}\n')
    adopted = manifest.Manifest(
        version="0.0.1",
        configs=("markdownlint",),
        python_dest=".",
        typescript_dest=".",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render())
    (tmp_path / ".markdownlint.yaml").write_text("stale\n")

    plan = upgrade.build_plan(tmp_path)

    assert not plan.ecosystems.python
    assert not plan.ecosystems.typescript
    assert plan.ecosystems.python_root is None
    assert plan.ecosystems.typescript_install_root is None
    precommit = next(contents for path, contents in plan.scaffold_plan.writes if path.name == ".pre-commit-config.yaml")
    assert f"uvx --from sarj-lint-configs=={manifest.adopted_version()}" in precommit
    assert "uv run --frozen sarj-standards" not in precommit


def test_upgrade_repairs_the_bundle_without_losing_manifest_extensions(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)

    status = upgrade.apply(upgrade.build_plan(tmp_path), install=False)

    assert status == 0
    manifest_text = (tmp_path / manifest.MANIFEST_NAME).read_text(encoding="utf-8")
    assert f'version = "{manifest.adopted_version()}"' in manifest_text
    assert "[consumer]\nkeep = true" in manifest_text
    assert {finding.id for finding in doctor.diagnose(tmp_path) if finding.level is doctor.Level.DRIFT} == {
        "doctor.python.bundle-missing"
    }


def test_legacy_upgrade_detects_and_persists_lefthook_manager(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    manifest_path = tmp_path / manifest.MANIFEST_NAME
    text = manifest_path.read_text(encoding="utf-8")
    text = text.replace('\n[hooks]\nmanager = "pre-commit"\n', "\n")
    manifest_path.write_text(text, encoding="utf-8")
    (tmp_path / "lefthook.yml").write_text(
        "pre-commit:\n  commands:\n    standards:\n      run: sarj-standards check --staged\n", encoding="utf-8"
    )

    plan = upgrade.build_plan(tmp_path)

    assert plan.adopted.hook_manager == "lefthook"
    assert '[hooks]\nmanager = "lefthook"' in plan.manifest_text


def test_upgrade_repairs_preexisting_replacement_ruff_policy(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "app"\nversion = "0.1.0"\n\n'
        '[tool.ruff]\nextend = ".ruff-strict.toml"\n\n'
        '[tool.ruff.lint]\nselect = ["ALL"]\nignore = ["D"]\n',
        encoding="utf-8",
    )

    plan = upgrade.build_plan(tmp_path)

    assert "repair adoption wiring" in upgrade.render(plan.changes)
    assert upgrade.apply(plan, install=False) == 0
    updated = pyproject.read_text(encoding="utf-8")
    assert 'extend-select = ["ALL"]' in updated
    assert 'extend-ignore = ["D"]' in updated


def test_upgrade_no_install_skips_dependency_install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    install_values: list[bool] = []

    def apply_without_side_effects(_plan: upgrade.UpgradePlan, *, install: bool = True) -> int:
        install_values.append(install)
        return 0

    monkeypatch.setattr(upgrade, "apply", apply_without_side_effects)

    assert cli.main(["upgrade", "--offline", "--no-install", "--dest", str(tmp_path)]) == 0
    assert install_values == [False]


def test_upgrade_no_install_keeps_valid_config_with_pending_dependency_drift(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)

    status = cli.main(["update", "--offline", "--no-install", str(tmp_path)])

    assert status == 0
    assert f'version = "{manifest.adopted_version()}"' in (tmp_path / manifest.MANIFEST_NAME).read_text(
        encoding="utf-8"
    )
    pending = upgrade.pending_install_findings(tmp_path)
    assert {finding.id for finding in pending} == {"doctor.python.bundle-missing"}


def test_upgrade_no_install_explains_incomplete_setup_and_next_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _outdated_python_repo(tmp_path)

    status = cli.main(["upgrade", "--offline", "--no-install", "--dest", str(tmp_path)])

    output = capsys.readouterr().out
    assert status == 0
    assert "updated configuration:" in output
    assert "setup is incomplete (1 dependency finding(s))" in output
    assert "pending: doctor.python.bundle-missing" in output
    assert "uv add --dev" in output
    assert "then `sarj-standards doctor`" in output
    assert "upgraded:" not in output


def test_upgrade_with_install_still_rolls_back_dependency_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _outdated_python_repo(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    finding = doctor.Finding(
        doctor.Level.DRIFT,
        "pyproject.toml",
        "forced missing dependency",
        "doctor.python.bundle-missing",
    )

    def execute(_commands: object) -> int:
        return 0

    def diagnose(_root: Path) -> list[doctor.Finding]:
        return [finding]

    monkeypatch.setattr(upgrade.lifecycle, "execute", execute)
    monkeypatch.setattr(doctor, "diagnose", diagnose)

    assert upgrade.apply(upgrade.build_plan(tmp_path), install=True) == 1
    assert {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()} == before


def test_upgrade_no_install_rolls_back_when_dependency_and_configuration_drift_remain(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _outdated_python_repo(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    findings = [
        doctor.Finding(
            doctor.Level.DRIFT,
            "pyproject.toml",
            "forced missing dependency",
            "doctor.python.bundle-missing",
        ),
        doctor.Finding(doctor.Level.DRIFT, "eslint.config.mjs", "forced broken wiring", "doctor.eslint.wiring"),
    ]

    def diagnose(_root: Path) -> list[doctor.Finding]:
        return findings

    monkeypatch.setattr(doctor, "diagnose", diagnose)

    assert upgrade.apply(upgrade.build_plan(tmp_path), install=False) == 1
    assert {path: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()} == before


def test_upgrade_check_explains_doctor_drift_when_bundle_is_current(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _outdated_python_repo(tmp_path)
    assert upgrade.apply(upgrade.build_plan(tmp_path), install=False) == 0
    finding = doctor.Finding(
        doctor.Level.DRIFT,
        "package.json: eslint",
        "expected exact tested peer",
        "doctor.eslint.peer",
        "run `sarj-standards update`",
    )

    def diagnosed(_root: Path) -> list[doctor.Finding]:
        return [finding]

    monkeypatch.setattr(doctor, "diagnose", diagnosed)

    status = cli.main(["upgrade", "--offline", "--check", "--dest", str(tmp_path)])

    output = capsys.readouterr().out
    assert status == 1
    assert "already matches standards" not in output
    assert "bundle current:" in output
    assert "doctor found 1 configuration drift" in output
    assert "drift: doctor.eslint.peer package.json: eslint" in output
    assert "fix: run `sarj-standards update`" in output


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
    status = upgrade.apply(plan, install=False)
    remaining = [finding for finding in doctor.diagnose(tmp_path) if finding.level is doctor.Level.DRIFT]
    assert status == 0, remaining
    precommit = (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    workflow = (workflows / "standards.yml").read_text(encoding="utf-8")
    package_json = (tmp_path / "package.json").read_text(encoding="utf-8")
    assert "uv run --frozen sarj-standards check --staged" in precommit
    assert "sarj-standards-drift" not in precommit
    assert f"sarj-lint-configs=={lint_configs}" in workflow
    assert f"sarj-lint-configs=={lint_configs}" in package_json
    assert "verbose: true" in (tmp_path / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert f"sarj-python-lint=={python_lint}" in pyproject.read_text(encoding="utf-8")
    assert f"sarj-python-lint=={python_lint}" in (tmp_path / "requirements-dev.txt").read_text(encoding="utf-8")
    assert {finding.id for finding in doctor.diagnose(tmp_path) if finding.level is doctor.Level.DRIFT} == {
        "doctor.python.bundle-missing"
    }


def test_upgrade_migrates_plain_official_remote_umbrella_hook(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n"
        "  - repo: https://github.com/pre-commit/pre-commit-hooks\n"
        "    rev: v5.0.0\n"
        "    hooks:\n"
        "      - id: trailing-whitespace\n"
        "  - repo: 'https://github.com/sarj-ai/standards.git'\n"
        "    rev: lint-configs-v0.1.0\n"
        "    hooks:\n"
        "      - id: sarj-standards\n"
        "\n"
        "# Keep this pre-commit setting comment.\n"
        "default_stages: [pre-commit, pre-push]\n"
        "ci:\n"
        "  autofix_prs: false\n",
        encoding="utf-8",
    )

    assert upgrade.apply(upgrade.build_plan(tmp_path), install=False) == 0

    migrated = config.read_text(encoding="utf-8")
    assert "pre-commit/pre-commit-hooks" in migrated
    assert "github.com/sarj-ai/standards" not in migrated
    assert migrated.count("id: sarj-standards-check") == 1
    assert "check --staged --" in migrated
    assert "# Keep this pre-commit setting comment." in migrated
    assert "default_stages: [pre-commit, pre-push]" in migrated
    assert "  autofix_prs: false" in migrated
    before = migrated
    assert upgrade.apply(upgrade.build_plan(tmp_path), install=False) == 0
    assert config.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("item_indent", [0, 4])
def test_upgrade_preserves_existing_precommit_repo_indentation(tmp_path: Path, item_indent: int) -> None:
    _outdated_python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    item = " " * item_indent
    field = " " * (item_indent + 2)
    hook = " " * (item_indent + 4)
    config.write_text(
        "repos:\n"
        f"{item}- repo: https://github.com/sarj-ai/standards\n"
        f"{field}rev: lint-configs-v0.1.0\n"
        f"{field}hooks:\n"
        f"{hook}- id: sarj-standards\n",
        encoding="utf-8",
    )

    assert upgrade.apply(upgrade.build_plan(tmp_path), install=False) == 0

    migrated = config.read_text(encoding="utf-8")
    loaded: object = yaml.safe_load(migrated)  # pyright: ignore[reportAny] -- validate the emitted YAML boundary.
    assert isinstance(loaded, dict)
    assert f"{item}- repo: local\n" in migrated
    assert migrated.count("id: sarj-standards-check") == 1


def test_upgrade_refuses_to_expand_custom_remote_hook_scope(tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    config = tmp_path / ".pre-commit-config.yaml"
    config.write_text(
        "repos:\n"
        "  - repo: https://github.com/sarj-ai/standards\n"
        "    rev: python-v0.1.0\n"
        "    hooks:\n"
        "      - id: sarj-no-comment-cruft\n"
        "        exclude: ^generated/\n",
        encoding="utf-8",
    )
    before = config.read_bytes()

    with pytest.raises(ValueError, match="preserve its scope manually"):
        upgrade.build_plan(tmp_path)

    assert config.read_bytes() == before


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


def test_upgrade_surfaces_incomplete_rollback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _outdated_python_repo(tmp_path)
    plan = upgrade.build_plan(tmp_path)
    conflict = tmp_path / manifest.MANIFEST_NAME

    def failed_apply(
        _plan: upgrade.UpgradePlan,
        _file_transaction: transaction.FileTransaction,
        *,
        install: bool,
    ) -> int:
        _ = install
        return 1

    def incomplete(_transaction: transaction.FileTransaction) -> transaction.RollbackReport:
        return transaction.RollbackReport((transaction.RollbackIssue(conflict, "changed concurrently"),))

    monkeypatch.setattr(upgrade, "_apply_and_validate", failed_apply)
    monkeypatch.setattr(transaction.FileTransaction, "rollback", incomplete)

    with pytest.raises(OSError, match=r"upgrade recovery incomplete.*changed concurrently"):
        upgrade.apply(plan, install=False)
