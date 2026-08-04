from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs.doctor import Level, check_pyright_deprecated, check_ruff_policy_authority


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


@pytest.mark.parametrize("key", ["ignore", "select"])
def test_doctor_rejects_replacement_rule_policy_in_extending_ruff_config(tmp_path: Path, key: str) -> None:
    (tmp_path / "pyproject.toml").write_text(
        f'[tool.ruff]\nextend = ".ruff-strict.toml"\n\n[tool.ruff.lint]\n{key} = ["ALL"]\n',
        encoding="utf-8",
    )

    findings = list(check_ruff_policy_authority(tmp_path))

    assert [finding.level for finding in findings] == [Level.DRIFT]
    assert findings[0].where == f"pyproject.toml: [tool.ruff.lint].{key}"
    assert f"use `extend-{key}`" in findings[0].detail


def test_doctor_accepts_additive_rule_policy_in_extending_ruff_config(tmp_path: Path) -> None:
    (tmp_path / "ruff.toml").write_text(
        'extend = ".ruff-strict.toml"\n\n[lint]\nextend-select = ["B904"]\nextend-ignore = ["D417"]\n',
        encoding="utf-8",
    )

    assert not list(check_ruff_policy_authority(tmp_path))


def test_doctor_rejects_multiple_ruff_policy_files(tmp_path: Path) -> None:
    root_config = tmp_path / "python" / "pyproject.toml"
    root_config.parent.mkdir()
    root_config.write_text('[tool.ruff]\nextend = ".ruff-strict.toml"\n', encoding="utf-8")
    child_config = tmp_path / "python" / "agent" / "pyproject.toml"
    child_config.parent.mkdir()
    child_config.write_text('[tool.ruff]\nextend = "../pyproject.toml"\n', encoding="utf-8")

    findings = list(check_ruff_policy_authority(tmp_path))

    assert [finding.where for finding in findings] == ["python/agent/pyproject.toml: Ruff config"]
    assert "split" in findings[0].detail
    assert "python/pyproject.toml" in findings[0].detail


def test_doctor_accepts_one_standalone_ruff_config(tmp_path: Path) -> None:
    (tmp_path / "ruff.toml").write_text('[lint]\nselect = ["ALL"]\n', encoding="utf-8")

    assert not list(check_ruff_policy_authority(tmp_path))


def test_doctor_rejects_consumer_config_that_reenables_conflicting_docstring_rules(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nextend = ".ruff-strict.toml"\n\n[tool.ruff.lint]\nselect = ["ALL"]\nignore = ["D417"]\n',
        encoding="utf-8",
    )

    findings = list(check_ruff_policy_authority(tmp_path))

    assert {finding.where for finding in findings} == {
        "pyproject.toml: [tool.ruff.lint].ignore",
        "pyproject.toml: [tool.ruff.lint].select",
    }
    assert all(finding.level is Level.DRIFT for finding in findings)
    assert all("canonical config remains authoritative" in finding.detail for finding in findings)
