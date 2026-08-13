"""Repository-controlled release builds do not inherit publishing credentials."""

from __future__ import annotations

from pathlib import Path

import pytest

from sarj_standards.libs.release import ProcessResult, credential_free_environment, run_build_process


@pytest.mark.parametrize("returncode", [True, False])
def test_process_result_rejects_boolean_return_codes(returncode: bool) -> None:
    with pytest.raises(TypeError, match="return code must be an integer"):
        ProcessResult(returncode)


def test_process_result_rejects_non_text_stdout() -> None:
    with pytest.raises(TypeError, match="process stdout must be text"):
        ProcessResult(0, b"output")  # pyright: ignore[reportArgumentType]


def test_process_result_rejects_non_text_stderr() -> None:
    with pytest.raises(TypeError, match="process stderr must be text"):
        ProcessResult(0, stderr=b"error")  # pyright: ignore[reportArgumentType]


def test_process_result_accepts_signal_return_codes_and_text_streams() -> None:
    assert ProcessResult(-15, "output", "terminated").returncode == -15


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
