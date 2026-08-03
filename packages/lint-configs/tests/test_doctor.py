from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs.doctor import Level, check_pyright_deprecated


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("name", "setting"),
    [
        pytest.param("pyrightconfig.json", '"reportDeprecated": false,', id="json-false"),
        pytest.param(".pyright-strict.json", '"reportDeprecated": "warning",', id="json-warning"),
        pytest.param("pyproject.toml", 'reportDeprecated = "none"', id="toml-none"),
    ],
)
def test_doctor_reports_deprecated_api_protection_that_is_not_an_error(tmp_path: Path, name: str, setting: str) -> None:
    _ = (tmp_path / name).write_text(f"{setting}\n", encoding="utf-8")

    findings = list(check_pyright_deprecated(tmp_path))

    assert [finding.level for finding in findings] == [Level.DRIFT]
    assert "reportDeprecated" in findings[0].where
    assert "restore it to keep deprecated APIs visible" in findings[0].detail


@pytest.mark.parametrize(
    ("name", "setting"),
    [
        pytest.param("pyrightconfig.json", '"reportDeprecated": "error",', id="json"),
        pytest.param("pyproject.toml", 'reportDeprecated = "error"', id="toml"),
        pytest.param("pyproject.toml", "reportDeprecated = 'error'", id="toml-single-quoted"),
    ],
)
def test_doctor_accepts_deprecated_api_protection_at_error(tmp_path: Path, name: str, setting: str) -> None:
    _ = (tmp_path / name).write_text(f"{setting}\n", encoding="utf-8")

    assert not list(check_pyright_deprecated(tmp_path))
