"""The typed facade remains importable independently of argparse."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

import sarj_lint_configs
from sarj_lint_configs import api


if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


def test_every_declared_public_api_resolves() -> None:
    assert api.__all__
    assert all(hasattr(api, name) for name in api.__all__)
    assert len(api.__all__) == len(set(api.__all__))


def test_package_root_exposes_the_small_consumer_facade() -> None:
    assert sarj_lint_configs.Standards is api.Standards
    assert sarj_lint_configs.Result is api.Result
    assert sarj_lint_configs.UpdateTarget is api.UpdateTarget


def test_public_api_keeps_pre_facade_compatibility_exports() -> None:
    preferred = {
        "AnalysisReport",
        "Change",
        "Diagnostic",
        "Finding",
        "Inspection",
        "Result",
        "Standards",
        "Status",
        "to_json",
        "to_sarif",
        "__version__",
    }
    compatibility = {"RUFF_STRICT", "plan_upgrade", "check_text", "ReleaseTarget", "initialize", "sync_configs"}

    assert preferred | compatibility <= set(api.__all__)


def test_standards_facade_returns_typed_doctor_result(tmp_path: Path) -> None:
    result = api.Standards(tmp_path).doctor()

    assert not result.ok
    assert result.status is api.Status.DRIFT
    assert result.findings[0].id == "doctor.manifest.absent"


def test_standards_facade_rejects_selected_paths_outside_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")

    result = api.Standards(tmp_path).check([str(outside)])

    assert result.status is api.Status.INVALID
    assert result.exit_code == 2
    assert result.findings[0].id == "check.input.invalid"


def test_standards_facade_rejects_selected_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    link = tmp_path / "linked.py"
    link.symlink_to(source)

    result = api.Standards(tmp_path).check(["linked.py"])

    assert result.status is api.Status.INVALID
    assert "symlink" in result.findings[0].message


def test_standards_facade_enforces_selected_application_dependency_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    adopted = api.Manifest(
        version=api.__version__,
        configs=("markdownlint",),
        python_dest=".",
        typescript_dest=".",
        profile="application",
    )
    (tmp_path / ".sarj-standards.toml").write_text(adopted.render(), encoding="utf-8")
    package = tmp_path / "package.json"
    package.write_text('{"dependencies":{"moment":"1"}}\n', encoding="utf-8")

    def clean_check(_paths: Sequence[str]) -> int:
        return 0

    monkeypatch.setattr(api, "check", clean_check)

    result = api.Standards(tmp_path).check(["package.json"])

    assert result.status is api.Status.DRIFT
    assert [finding.id for finding in result.findings] == ["LIB102"]


def test_standards_facade_runs_eslint_for_selected_typescript(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "component.ts"
    source.write_text("export const value = 1;\n", encoding="utf-8")
    command = api.Command("ESLint", ("true",), tmp_path)

    def clean_check(_paths: Sequence[str]) -> int:
        return 0

    def selected(_root: Path, _paths: Sequence[str]) -> list[api.Command]:
        return [command]

    def execute(commands: Sequence[api.Command]) -> int:
        return 1 if list(commands) == [command] else 0

    monkeypatch.setattr(api, "check", clean_check)
    monkeypatch.setattr(api, "selected_eslint_commands", selected)
    monkeypatch.setattr(api, "execute", execute)

    result = api.Standards(tmp_path).check(["component.ts"])

    assert result.status is api.Status.DRIFT


def test_standards_facade_init_dry_run_never_writes(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n',
        encoding="utf-8",
    )

    result = api.Standards(tmp_path).init(dry_run=True)

    assert result.status is api.Status.CHANGED
    assert result.changes
    assert any(change.path == tmp_path / ".ruff-strict.toml" for change in result.changes)
    assert not (tmp_path / ".sarj-standards.toml").exists()


def test_standards_facade_init_exposes_project_roots_and_truthful_no_install_preview(tmp_path: Path) -> None:
    python_root = tmp_path / "python"
    python_root.mkdir()
    (python_root / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n',
        encoding="utf-8",
    )

    result = api.Standards(tmp_path).init(
        configs=("ruff",),
        python_root="python",
        install=False,
        dry_run=True,
    )

    assert result.status is api.Status.CHANGED
    assert any(change.path == python_root / ".ruff-strict.toml" for change in result.changes)
    assert all(change.action != "run" for change in result.changes)
    assert not (python_root / ".ruff-strict.toml").exists()


def test_standards_facade_init_dry_run_reports_invalid_plan(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.0.0"\nrequires-python = ">=3.14"\n', encoding="utf-8"
    )
    (tmp_path / ".pre-commit-config.yaml").write_text("repos: []\n", encoding="utf-8")
    (tmp_path / ".pre-commit-config.yml").write_text("repos: []\n", encoding="utf-8")

    result = api.Standards(tmp_path).init(dry_run=True, install=False)

    assert result.status is api.Status.INVALID
    assert result.exit_code == 2
    assert result.findings[0].id == "init.plan.invalid"
    assert "multiple pre-commit configurations" in result.findings[0].message


def test_standards_facade_update_returns_invalid_result_for_bad_manifest(tmp_path: Path) -> None:
    (tmp_path / ".sarj-standards.toml").write_text('version = "not a version"\n', encoding="utf-8")

    result = api.Standards(tmp_path).update(install=False, target=api.UpdateTarget.INSTALLED)

    assert result.status is api.Status.INVALID
    assert result.exit_code == 2
    assert result.findings[0].id == "update.plan.invalid"


def test_standards_facade_update_check_exposes_doctor_findings(tmp_path: Path) -> None:
    result = api.Standards(tmp_path).update(check_only=True, target=api.UpdateTarget.INSTALLED)

    assert result.status is api.Status.INVALID
    assert result.findings[0].id == "update.plan.invalid"


def test_standards_facade_update_targets_latest_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class EmptyPlan:
        changes: tuple[()] = ()

    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "upgraded", "")

    def plan(_root: Path) -> EmptyPlan:
        return EmptyPlan()

    def which(_name: str) -> str:
        return "/usr/bin/uvx"

    monkeypatch.setattr(api, "plan_upgrade", plan)
    monkeypatch.setattr("sarj_lint_configs.api.shutil.which", which)
    monkeypatch.setattr("sarj_lint_configs.api.subprocess.run", run)

    result = api.Standards(tmp_path).update(install=False)

    assert result.status is api.Status.CHANGED
    assert commands == [
        [
            "/usr/bin/uvx",
            "--refresh",
            "--from",
            "sarj-lint-configs",
            "sarj-standards",
            "update",
            "--offline",
            "--dest",
            str(tmp_path),
            "--no-install",
        ]
    ]


def test_standards_facade_installed_no_install_reports_dependency_setup_as_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class EmptyPlan:
        changes: tuple[()] = ()

    def plan(_root: Path) -> EmptyPlan:
        return EmptyPlan()

    pending = api.DoctorFinding(
        api.DoctorLevel.DRIFT,
        "pyproject.toml",
        "lint-configs pin is missing",
        "doctor.python.bundle-missing",
        "run uv add",
    )

    def apply(_plan: object, *, install: bool) -> int:
        _ = install
        return 0

    def diagnosed(_root: Path) -> list[api.DoctorFinding]:
        return [pending]

    monkeypatch.setattr(api, "plan_upgrade", plan)
    monkeypatch.setattr(api, "apply_upgrade", apply)
    monkeypatch.setattr(api, "diagnose", diagnosed)

    result = api.Standards(tmp_path).update(install=False, target=api.UpdateTarget.INSTALLED)

    assert result.ok
    assert result.findings[0].level == "warn"
    assert "intentionally skipped" in result.findings[0].message


def test_standards_facade_init_rejects_invalid_existing_manifest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "fixture"\nversion = "0.0.0"\n', encoding="utf-8")
    manifest = tmp_path / ".sarj-standards.toml"
    manifest.write_text("bad = [\n", encoding="utf-8")

    result = api.Standards(tmp_path).init(install=False, dry_run=True)

    assert result.status is api.Status.INVALID
    assert result.findings[0].id == "init.input.invalid"
    assert manifest.read_text(encoding="utf-8") == "bad = [\n"


@pytest.mark.parametrize("configs", [("bogus",), (), "ruff"], ids=("unknown", "empty", "string"))
def test_standards_facade_init_rejects_invalid_configs(tmp_path: Path, configs: object) -> None:
    result = api.Standards(tmp_path).init(configs=configs, install=False)  # type: ignore[arg-type]

    assert result.status is api.Status.INVALID
    assert result.findings[0].id == "init.input.invalid"


def test_standards_facade_init_rejects_invalid_runtime_profile(tmp_path: Path) -> None:
    result = api.Standards(tmp_path).init(profile="bogus", install=False)  # type: ignore[arg-type]

    assert result.status is api.Status.INVALID
    assert result.findings[0].id == "init.input.invalid"
