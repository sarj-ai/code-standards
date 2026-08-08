"""Repository-controlled release builds do not inherit publishing credentials."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sarj_standards.libs.release import ProcessResult, credential_free_environment, run_build_process


if TYPE_CHECKING:
    import pytest


def test_credential_free_environment_removes_common_secret_forms() -> None:
    environment = {
        "PATH": "/tools",
        "LANG": "C.UTF-8",
        "NPM_TOKEN": "npm-secret",
        "UV_PUBLISH_TOKEN": "pypi-secret",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "oidc-secret",
        "AWS_SECRET_ACCESS_KEY": "cloud-secret",
        "SERVICE_API_KEY": "api-secret",
        "SSH_AUTH_SOCK": "/private/agent.sock",
        "NPM_CONFIG_USERCONFIG": "/private/token-bearing-npmrc",
    }

    assert credential_free_environment(environment) == {"PATH": "/tools", "LANG": "C.UTF-8"}


def test_build_process_isolates_posix_and_windows_config_homes(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    def run(
        _argv: tuple[str, ...],
        *,
        cwd: Path,
        capture_output: bool,
        environment: dict[str, str] | None,
    ) -> ProcessResult:
        _ = cwd, capture_output
        assert environment is not None
        seen.update(environment)
        return ProcessResult(0)

    monkeypatch.setattr("sarj_standards.libs.release.process.run_process_environment", run)

    assert run_build_process(("build",), cwd=Path()) == ProcessResult(0)
    assert seen["HOME"] == seen["USERPROFILE"] == seen["APPDATA"] == seen["LOCALAPPDATA"]
