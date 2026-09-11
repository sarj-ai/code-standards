from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.repository.ruff_freshness import evaluate


if TYPE_CHECKING:
    from pathlib import Path


def _write_manifests(root: Path, version: str) -> None:
    for relative in (
        "packages/bootstrap/pyproject.toml",
        "packages/python/pyproject.toml",
        "packages/sql/pyproject.toml",
        "packages/iac/pyproject.toml",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"[dependency-groups]\ndev = ['ruff>={version}']\n", encoding="utf-8")
    standards = root / "packages/standards/pyproject.toml"
    standards.parent.mkdir(parents=True, exist_ok=True)
    standards.write_text(f"[project]\ndependencies = ['ruff=={version}']\n", encoding="utf-8")


def test_evaluate_accepts_one_synchronized_latest_stable_version(tmp_path: Path) -> None:
    _write_manifests(tmp_path, "0.16.7")

    result = evaluate(tmp_path, {"info": {"version": "0.16.7"}})

    assert result.current
    assert result.latest == "0.16.7"


def test_evaluate_reports_every_stale_manifest(tmp_path: Path) -> None:
    _write_manifests(tmp_path, "0.16.5")

    result = evaluate(tmp_path, {"info": {"version": "0.16.7"}})

    assert not result.current
    assert len(result.stale) == 5


@pytest.mark.parametrize("version", ["0.17.0rc1", "0.17.0.dev1"])
def test_evaluate_rejects_pypi_prereleases(tmp_path: Path, version: str) -> None:
    _write_manifests(tmp_path, "0.16.7")

    with pytest.raises(ValueError, match="not stable"):
        evaluate(tmp_path, {"info": {"version": version}})
