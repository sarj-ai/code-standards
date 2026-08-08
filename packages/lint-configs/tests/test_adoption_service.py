"""Typed adoption services own complete mutations independently of the CLI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sarj_lint_configs.libs.adoption import lifecycle, manifest
from sarj_lint_configs.libs.adoption.service import (
    InitFailure,
    SyncOutcome,
    apply_init,
    apply_sync,
    plan_init,
    plan_sync,
)


if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    import pytest


def _python_project(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "consumer"\nversion = "0.1.0"\nrequires-python = ">=3.14"\n',
        encoding="utf-8",
    )


def test_sync_service_plans_and_applies_without_cli_state(tmp_path: Path) -> None:
    plan = plan_sync(tmp_path, configs=("ruff", "ruff"))

    assert tuple(target.name for target in plan.targets) == ("ruff",)
    result = apply_sync(plan)

    assert result.status == 0
    assert result.count(SyncOutcome.WRITTEN) == 1
    assert (tmp_path / ".ruff-strict.toml").is_file()


def test_sync_service_reports_current_config_as_ok_without_rewriting(tmp_path: Path) -> None:
    plan = plan_sync(tmp_path, configs=("ruff",))
    first = apply_sync(plan)
    before = plan.targets[0].destination.stat().st_mtime_ns

    second = apply_sync(plan, force=True)

    assert first.count(SyncOutcome.WRITTEN) == 1
    assert second.count(SyncOutcome.OK) == 1
    assert second.count(SyncOutcome.WRITTEN) == 0
    assert plan.targets[0].destination.stat().st_mtime_ns == before


def test_init_service_applies_configs_wiring_and_manifest(tmp_path: Path) -> None:
    _python_project(tmp_path)
    plan = plan_init(tmp_path)

    result = apply_init(plan, install=False)

    assert result.status == 0
    assert (tmp_path / ".ruff-strict.toml").is_file()
    assert (tmp_path / ".pyright-strict.json").is_file()
    assert manifest.load(tmp_path) is not None
    assert 'extend = ".ruff-strict.toml"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


def test_init_service_rejects_absent_target_created_after_planning(tmp_path: Path) -> None:
    _python_project(tmp_path)
    plan = plan_init(tmp_path)
    target = tmp_path / ".ruff-strict.toml"
    target.write_text("late user file\n", encoding="utf-8")

    result = apply_init(plan, install=False)

    assert result.status == 2
    assert result.error is not None
    assert "stale" in result.error
    assert target.read_text(encoding="utf-8") == "late user file\n"


def test_init_service_rolls_back_every_file_when_install_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _python_project(tmp_path)
    original = (tmp_path / "pyproject.toml").read_bytes()
    plan = plan_init(tmp_path)

    def fail_install(_commands: Iterable[lifecycle.Command]) -> int:
        return 7

    monkeypatch.setattr(lifecycle, "execute", fail_install)
    result = apply_init(plan)

    assert result.status == 2
    assert result.error == "dependency or hook installer exited with status 7"
    assert result.failure is InitFailure.INSTALL
    assert (tmp_path / "pyproject.toml").read_bytes() == original
    assert not (tmp_path / ".ruff-strict.toml").exists()
    assert not (tmp_path / manifest.MANIFEST_NAME).exists()
