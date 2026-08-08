"""Compatibility bundles depend only on exact, authoritative publications."""

from __future__ import annotations

from datetime import timedelta
import json
from typing import TYPE_CHECKING

import pytest

from sarj_lint_configs.libs.release.registry import (
    RegistryRequirement,
    lint_config_requirements,
    require_lint_config_dependencies,
    target_requirement,
    wait_for_lint_config_dependencies,
)


if TYPE_CHECKING:
    from pathlib import Path


def _bundle(root: Path, *, python_pin: str = "sarj-python-lint==1.2.3") -> None:
    manifest = root / "packages/lint-configs/pyproject.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        f'[project]\nname = "sarj-lint-configs"\nversion = "4.0.0"\ndependencies = ["{python_pin}", "ruff==1.0.0"]\n',
        encoding="utf-8",
    )
    peers = root / "packages/lint-configs/src/sarj_lint_configs/configs/eslint.peers.json"
    peers.parent.mkdir(parents=True)
    peers.write_text(json.dumps({"peers": {"@sarj/eslint-plugin": "9.8.7"}}), encoding="utf-8")


def test_lint_config_requirements_read_exact_pypi_and_npm_pins(tmp_path: Path) -> None:
    _bundle(tmp_path)

    assert lint_config_requirements(tmp_path) == (
        RegistryRequirement("npm", "@sarj/eslint-plugin", "9.8.7"),
        RegistryRequirement("pypi", "sarj-python-lint", "1.2.3"),
    )


def test_lint_config_requirements_reject_nonexact_sibling_pin(tmp_path: Path) -> None:
    _bundle(tmp_path, python_pin="sarj-python-lint>=1.2.3")

    with pytest.raises(ValueError, match="must use an exact pin"):
        lint_config_requirements(tmp_path)


def test_lint_config_preflight_reports_the_first_missing_publication(tmp_path: Path) -> None:
    _bundle(tmp_path)

    with pytest.raises(ValueError, match=r"npm publication is unavailable: @sarj/eslint-plugin@9\.8\.7"):
        require_lint_config_dependencies(tmp_path, checker=lambda requirement: requirement.registry == "pypi")


def test_target_requirement_uses_authoritative_manifest_version(tmp_path: Path) -> None:
    manifest = tmp_path / "packages/python/pyproject.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('[project]\nname = "sarj-python-lint"\nversion = "2.3.4"\n', encoding="utf-8")

    assert target_requirement(tmp_path, "python") == RegistryRequirement("pypi", "sarj-python-lint", "2.3.4")


def test_lint_config_preflight_waits_for_registry_propagation(tmp_path: Path) -> None:
    _bundle(tmp_path)
    python_attempts = iter((False, False, True))
    delays: list[float] = []

    def checker(requirement: RegistryRequirement) -> bool:
        return True if requirement.registry == "npm" else next(python_attempts)

    requirements = wait_for_lint_config_dependencies(
        tmp_path,
        attempts=3,
        delay=timedelta(milliseconds=250),
        checker=checker,
        sleeper=delays.append,
    )

    assert requirements == lint_config_requirements(tmp_path)
    assert delays == [0.25, 0.25]


def test_lint_config_preflight_fails_after_its_bounded_attempts(tmp_path: Path) -> None:
    _bundle(tmp_path)
    delays: list[float] = []

    with pytest.raises(ValueError, match=r"after 2 attempt\(s\).*sarj-python-lint@1\.2\.3"):
        _ = wait_for_lint_config_dependencies(
            tmp_path,
            attempts=2,
            delay=timedelta(milliseconds=500),
            checker=lambda requirement: requirement.registry == "npm",
            sleeper=delays.append,
        )

    assert delays == [0.5]
