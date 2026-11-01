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


@pytest.mark.parametrize("name", ["wrangler.toml", "wrangler.json", "wrangler.jsonc"])
def test_allows_only_posthog_public_project_tokens(tmp_path: Path, name: str) -> None:
    token = "phc_" + "a" * 40
    source = (
        f'POSTHOG_API_KEY = "{token}"' if name.endswith(".toml") else f'{{"vars": {{"POSTHOG_API_KEY": "{token}"}}}}'
    )
    result = _check(tmp_path, {name: source})
    assert result.returncode == 0
    assert not result.stderr


@pytest.mark.parametrize("prefix", ["phx_", "phs_", "pha_", "phr_", "private_"])
def test_posthog_binding_name_cannot_hide_private_credentials(tmp_path: Path, prefix: str) -> None:
    value = prefix + "b" * 40
    result = _check(tmp_path, {"wrangler.toml": f'POSTHOG_API_KEY = "{value}"'})
    assert result.returncode == 1
    assert "POSTHOG_API_KEY" in result.stderr
    assert value not in result.stdout + result.stderr


@pytest.mark.parametrize("value", ["phc_short", "phc_" + "a" * 129, "phc_" + "a" * 40 + " private"])
def test_malformed_posthog_values_do_not_gain_an_exception(tmp_path: Path, value: str) -> None:
    result = _check(tmp_path, {"wrangler.toml": f'POSTHOG_API_KEY = "{value}"'})
    assert result.returncode == 1
    assert value not in result.stdout + result.stderr


def test_public_posthog_token_does_not_hide_an_adjacent_worker_secret(tmp_path: Path) -> None:
    source = 'POSTHOG_API_KEY = "phc_' + "a" * 40 + f'"\nTOOL_AUTH_TOKEN = "{_PRIVATE_VALUE}"'
    result = _check(tmp_path, {"wrangler.toml": source})
    assert result.returncode == 1
    assert "TOOL_AUTH_TOKEN" in result.stderr
    assert "POSTHOG_API_KEY" not in result.stderr
    assert _PRIVATE_VALUE not in result.stdout + result.stderr


def test_posthog_project_format_does_not_exempt_a_different_binding(tmp_path: Path) -> None:
    value = "phc_" + "a" * 40
    result = _check(tmp_path, {"wrangler.toml": f'TOOL_AUTH_TOKEN = "{value}"'})
    assert result.returncode == 1
    assert "TOOL_AUTH_TOKEN" in result.stderr
    assert value not in result.stdout + result.stderr
