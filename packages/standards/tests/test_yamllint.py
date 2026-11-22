from __future__ import annotations

from importlib.resources import files
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "yamllint.yaml"
    path.write_text(
        files("sarj_standards").joinpath("configs/yamllint.strict.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return path


def _run(config: Path, source: str, *options: str) -> subprocess.CompletedProcess[str]:
    path = config.with_name("example.yaml")
    path.write_text(source, encoding="utf-8")
    return subprocess.run(
        (sys.executable, "-m", "yamllint", "--config-file", str(config), "--format", "parsable", *options, str(path)),
        cwd=config.parent,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        ("#comment\nvalue: true\n", "comments"),
        ("root:\n  value: true\n # misaligned\n", "comments-indentation"),
        ("value: yes\n", "truthy"),
    ],
)
def test_managed_yaml_policies_block_the_normal_cli(config: Path, source: str, rule: str) -> None:
    result = _run(config, source)

    assert result.returncode == 1
    assert f"({rule})" in result.stdout
    assert "[error]" in result.stdout


@pytest.mark.parametrize(
    "source",
    [
        "# Comment\nvalue: true\n",
        "root:\n  # Nested comment\n  value: false\n",
        "on:\n  push:\n    branches: [main]\n",
        "value: !!str yes\n",
        "%YAML 1.2\n---\nvalue: yes\n",
        "value: yes  # yamllint disable-line rule:truthy\n",
    ],
)
def test_managed_yaml_boundaries_and_exact_suppression_remain_valid(config: Path, source: str) -> None:
    result = _run(config, source, "--strict")

    assert result.returncode == 0, result.stdout + result.stderr


def test_malformed_yaml_cannot_qualify(config: Path) -> None:
    result = _run(config, "items: [\n")

    assert result.returncode == 1
    assert "[error]" in result.stdout
    assert "syntax" in result.stdout


def test_unknown_yaml_rule_configuration_cannot_qualify(config: Path) -> None:
    config.write_text("rules:\n  unknown-sarj-rule: enable\n", encoding="utf-8")

    result = _run(config, "value: true\n")

    assert result.returncode != 0
    assert "invalid config" in result.stderr
