from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest


if TYPE_CHECKING:
    from collections.abc import Mapping

_SCRIPT = Path(__file__).resolve().parents[4] / ".github/scripts/check-public-config.py"
_PRIVATE_VALUE = "private-fixture-value"


def _check(project: Path, files: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    for name, source in files.items():
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    subprocess.run(["git", "init", "--quiet"], cwd=project, check=True)
    subprocess.run(["git", "add", "--", "."], cwd=project, check=True)
    return subprocess.run([sys.executable, str(_SCRIPT)], cwd=project, capture_output=True, text=True, check=False)


@pytest.mark.parametrize(
    ("name", "source", "detail"),
    [
        pytest.param(
            "client.ts",
            f'export const NEXT_PUBLIC_SERVICE_ROLE_KEY = "{_PRIVATE_VALUE}";',
            "NEXT_PUBLIC_SERVICE_ROLE_KEY",
            id="public-client-secret",
        ),
        pytest.param(
            "wrangler.toml",
            f'TOOL_AUTH_TOKEN = "{_PRIVATE_VALUE}"',
            "TOOL_AUTH_TOKEN",
            id="literal-worker-secret",
        ),
        pytest.param(
            "config.swift",
            f'let toolAuthToken = "{_PRIVATE_VALUE}"',
            "shared voice/tool credentials",
            id="compiled-native-secret",
        ),
    ],
)
def test_reports_binding_names_without_secret_values(tmp_path: Path, name: str, source: str, detail: str) -> None:
    result = _check(tmp_path, {name: source})
    assert result.returncode == 1
    assert name in result.stderr
    assert detail in result.stderr
    assert _PRIVATE_VALUE not in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("name", "source"),
    [
        pytest.param("client.ts", 'const NEXT_PUBLIC_FIREBASE_API_KEY = "browser-key";', id="browser-key"),
        pytest.param("wrangler.toml", 'TOOL_AUTH_TOKEN = "${TOOL_AUTH_TOKEN}"', id="encrypted-binding-reference"),
        pytest.param("wrangler.jsonc", '{"TOOL_AUTH_TOKEN": "{{binding}}"}', id="template-binding-reference"),
        pytest.param("wrangler.toml", 'TOOL_AUTH_TOKEN = "placeholder"', id="placeholder"),
        pytest.param("README.md", "NEXT_PUBLIC_SERVICE_ROLE_KEY", id="excluded-documentation"),
        pytest.param("test_public_config.py", "NEXT_PUBLIC_SERVICE_ROLE_KEY", id="existing-test-exclusion"),
    ],
)
def test_retains_existing_allowed_inputs(tmp_path: Path, name: str, source: str) -> None:
    result = _check(tmp_path, {name: source})
    assert result.returncode == 0
    assert result.stdout == "Public credential policy passed\n"
    assert not result.stderr
