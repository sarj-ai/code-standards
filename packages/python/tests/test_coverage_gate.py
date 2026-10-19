from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.fixture
def coverage_project(tmp_path: Path) -> Path:
    project = tmp_path / "packages/python"
    tests = project / "tests"
    tests.mkdir(parents=True)
    shutil.copyfile(Path(__file__).with_name("conftest.py"), tests / "conftest.py")
    (project / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    (tests / "test_probe.py").write_text("def test_probe():\n    pass\n")
    return project


def _pytest(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *arguments],
        cwd=project,
        env={**os.environ, "PYTEST_ADDOPTS": ""},  # ruff: ignore[banned-api] -- isolate pytest filters, retain runtime.
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_collection_does_not_require_rule_execution(coverage_project: Path) -> None:
    result = _pytest(coverage_project, "--collect-only")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_probe.py::test_probe" in result.stdout
    assert "rules whose tests do not exercise them" not in result.stdout


def test_normal_run_still_requires_both_rule_directions(coverage_project: Path) -> None:
    result = _pytest(coverage_project)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "never makes it report" in result.stdout
    assert "Every rule needs at least one case it flags" in result.stdout


def test_collection_error_still_fails(coverage_project: Path) -> None:
    (coverage_project / "tests/test_probe.py").write_text("def broken(\n")

    result = _pytest(coverage_project, "--collect-only")

    assert result.returncode != 0
    assert "SyntaxError" in result.stdout
