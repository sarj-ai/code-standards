from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.linting.external import run_process


if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("data_directory", ["installed", "installed tools", "nested/installed"])
@pytest.mark.parametrize("installation_key", ["MISE_DATA_DIR", "MISE_INSTALLS_DIR", "XDG_DATA_HOME"])
def test_native_lookup_preserves_explicit_mise_installation_scope_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, data_directory: str, installation_key: str
) -> None:
    installed = tmp_path / data_directory
    installed.mkdir(parents=True)
    for key in ("MISE_DATA_DIR", "MISE_INSTALLS_DIR", "XDG_DATA_HOME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(installation_key, str(installed))
    for key in ("MISE_GITHUB_TOKEN", "SARJ_AUDIT_SECRET", "MISE_CONFIG_DIR", "TFLINT_PLUGIN_DIR"):
        monkeypatch.setenv(key, "fixture-sensitive-value")
    script = tmp_path / "observe_native_environment.py"
    script.write_text(
        """import json
import os
keys = ("MISE_DATA_DIR", "MISE_INSTALLS_DIR", "XDG_DATA_HOME", "MISE_GITHUB_TOKEN", "SARJ_AUDIT_SECRET", "MISE_CONFIG_DIR", "TFLINT_PLUGIN_DIR")
print(json.dumps({key: os.getenv(key) for key in keys}))
""",
        encoding="utf-8",
    )

    output = run_process((sys.executable, str(script)), cwd=tmp_path)

    expected_environment: dict[str, str | None] = {
        "MISE_DATA_DIR": None,
        "MISE_INSTALLS_DIR": None,
        "XDG_DATA_HOME": None,
        "MISE_GITHUB_TOKEN": None,
        "SARJ_AUDIT_SECRET": None,
        "MISE_CONFIG_DIR": None,
        "TFLINT_PLUGIN_DIR": None,
    }
    expected_environment[installation_key] = str(installed)
    assert output.returncode == 0
    assert json.loads(output.stdout) == expected_environment
