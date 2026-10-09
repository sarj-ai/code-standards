from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sarj_python_lint.__main__ import analyze


if TYPE_CHECKING:
    from pathlib import Path


_RULE_ORDERS = (
    ("no-hidden-constructor-fallback", "prefer-required-constructor-parameters"),
    ("prefer-required-constructor-parameters", "no-hidden-constructor-fallback"),
)


def _settings_project(tmp_path: Path, *, suppression: str = "") -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'example'\nversion = '0.1.0'\n")
    package = tmp_path / "app"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "config.py").write_text(
        "from pydantic_settings import BaseSettings\n"
        "class Settings(BaseSettings):\n"
        "    MODEL: str = 'model'\n"
        "settings = Settings()\n"
    )
    source = (
        "from app.config import settings\n"
        "class Service:\n"
        f"    def __init__(self, *, model: str | None = None, label: str = ''):{suppression}\n"
        "        self.model = model or settings.MODEL\n"
        "        self.label = label\n"
        "class Other:\n"
        "    def __init__(self, value=None): ...\n"
        "service = Service(model='explicit', label='explicit')\n"
    )
    path = package / "service.py"
    path.write_text(source)
    return path


@pytest.mark.parametrize("rules", _RULE_ORDERS, ids=("specific-first", "generic-first"))
def test_settings_fallback_owns_only_the_same_parameter(tmp_path: Path, rules: tuple[str, str]) -> None:
    path = _settings_project(tmp_path)
    source = path.read_text()
    findings = analyze(list(rules), [path])
    signature = source.splitlines()[2]
    assert sorted((finding.code, finding.line, finding.col) for finding in findings) == [
        ("SARJ095", 3, signature.index("model:") + 1),
        ("SARJ468", 3, signature.index("label:") + 1),
        ("SARJ468", 7, source.splitlines()[6].index("value=") + 1),
    ]


@pytest.mark.parametrize("rules", _RULE_ORDERS, ids=("specific-first", "generic-first"))
def test_suppressing_specific_rule_preserves_generic_review(tmp_path: Path, rules: tuple[str, str]) -> None:
    path = _settings_project(tmp_path, suppression="  # sarj-noqa: SARJ095 -- deliberate compatibility")
    source = path.read_text()
    findings = analyze(list(rules), [path])
    signature = source.splitlines()[2]
    expected = [
        ("SARJ468", 3, signature.index("model:") + 1),
        ("SARJ468", 3, signature.index("label:") + 1),
        ("SARJ468", 7, source.splitlines()[6].index("value=") + 1),
    ]
    assert [(finding.code, finding.line, finding.col) for finding in findings] == expected
    assert [(finding.code, finding.line, finding.col) for finding in analyze(list(rules), [path])] == expected
