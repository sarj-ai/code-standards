"""The typed facade remains importable independently of argparse."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_lint_configs import api


if TYPE_CHECKING:
    from pathlib import Path


def test_every_declared_public_api_resolves() -> None:
    assert api.__all__
    assert all(hasattr(api, name) for name in api.__all__)
    assert len(api.__all__) == len(set(api.__all__))


def test_public_api_keeps_pre_facade_compatibility_exports() -> None:
    preferred = {"Change", "Finding", "Inspection", "Result", "Standards", "Status", "__version__"}
    compatibility = {"RUFF_STRICT", "plan_upgrade", "check_text", "ReleaseTarget", "initialize", "sync_configs"}

    assert preferred | compatibility <= set(api.__all__)


def test_standards_facade_returns_typed_doctor_result(tmp_path: Path) -> None:
    result = api.Standards(tmp_path).doctor()

    assert result.ok
    assert result.status is api.Status.OK
    assert result.findings[0].id == "doctor.manifest.absent"


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
