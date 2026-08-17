"""Clean-break adoption must never leave an older tool config authoritative."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards._meta import CONFIGS_DIR
from sarj_standards.libs.adoption import doctor, manifest, scaffold
from sarj_standards.libs.linting import runner


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("name", [".ruff.toml", "ruff.toml"])
def test_setup_rejects_standalone_ruff_config_that_would_shadow_pyproject(tmp_path: Path, name: str) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '1'\n", encoding="utf-8")
    (tmp_path / name).write_text("line-length = 88\n", encoding="utf-8")

    plan = scaffold.build_plan(tmp_path, force=False)

    assert any("standalone config" in error and name in error for error in plan.errors)
    assert not any(path.name == "pyproject.toml" for path, _contents in (*plan.writes, *plan.edits))


def test_doctor_reports_standalone_ruff_config_that_bypasses_adopted_chain(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nextend = ".ruff-strict.toml"\n',
        encoding="utf-8",
    )
    (tmp_path / "ruff.toml").write_text("line-length = 88\n", encoding="utf-8")
    (tmp_path / ".ruff-strict.toml").write_bytes((CONFIGS_DIR / "ruff.strict.toml").read_bytes())
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=("ruff",),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    findings = doctor.diagnose(tmp_path)

    assert "doctor.ruff.ambiguous-config" in {finding.id for finding in findings}


@pytest.mark.parametrize("name", ["client.gen.ts", "client.generated.ts"])
def test_explicit_generated_client_file_is_ignored_like_directory_discovery(tmp_path: Path, name: str) -> None:
    generated = tmp_path / name
    generated.write_text("export const generated = true;\n", encoding="utf-8")

    assert runner.group_paths([str(generated)]) == runner.GroupedPaths()


def test_explicit_hands_off_generated_client_is_ignored(tmp_path: Path) -> None:
    generated = tmp_path / "client.py"
    generated.write_text("# AUTO-GENERATED; DO NOT EDIT.\nvalue = 1\n", encoding="utf-8")

    assert runner.group_paths([str(generated)]) == runner.GroupedPaths()


def test_setup_does_not_treat_a_direct_standards_command_as_canonical_ci(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '1'\n", encoding="utf-8")
    workflow = tmp_path / ".github" / "workflows" / "quality.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  quality:\n    steps:\n      - run: uv run sarj-standards --root . check\n",
        encoding="utf-8",
    )

    plan = scaffold.build_plan(tmp_path, force=False)

    generated = tmp_path / ".github" / "workflows" / "standards.yml"
    assert any(path == generated for path, _contents in plan.writes)


def test_setup_generates_ci_when_workflow_only_mentions_standards(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "quality.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  quality:\n    steps:\n      - name: sarj-standards check\n        run: echo check\n",
        encoding="utf-8",
    )

    plan = scaffold.build_plan(tmp_path, force=False, configs=("markdownlint",))

    assert any(path.name == "standards.yml" for path, _contents in plan.writes)


def test_doctor_rejects_a_direct_standards_command_as_noncanonical_ci(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "standards-ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  quality:\n    steps:\n      - run: |\n          uv run sarj-standards --root . check\n",
        encoding="utf-8",
    )
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=(),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    findings = doctor.diagnose(tmp_path)

    gates = [finding for finding in findings if finding.id == "doctor.ci.gate"]
    assert len(gates) == 1
    assert gates[0].level is doctor.Level.DRIFT


def test_doctor_reports_missing_ci_gate(tmp_path: Path) -> None:
    adopted = manifest.Manifest(
        version=manifest.adopted_version(),
        configs=(),
        python_dest=".",
        typescript_dest=".",
        hook_manager="none",
    )
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")

    findings = doctor.diagnose(tmp_path)

    gates = [finding for finding in findings if finding.id == "doctor.ci.gate"]
    assert len(gates) == 1
    assert gates[0].level is doctor.Level.DRIFT
