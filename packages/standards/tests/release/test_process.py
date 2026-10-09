from __future__ import annotations

from pathlib import Path
import sys

import pytest

from sarj_standards.libs.release import ProcessResult, credential_free_environment, run_build_process
from sarj_standards.libs.release.process import (
    ProcessBinaryResult,
    ProcessFailureError,
    run_binary_process,
    run_input_process,
)


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
        cwd: Path,  # ruff: ignore[unused-function-argument] -- The process adapter fixes this keyword.
        capture_output: bool,  # ruff: ignore[unused-function-argument] -- The process adapter fixes this keyword.
        environment: dict[str, str] | None,
    ) -> ProcessResult:
        assert environment is not None
        seen.update(environment)
        return ProcessResult(0)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test intercepts the subprocess environment boundary
        "sarj_standards.libs.release.process.run_process_environment", run
    )

    assert run_build_process(("build",), cwd=Path()) == ProcessResult(0)
    assert seen["HOME"] == seen["USERPROFILE"] == seen["APPDATA"] == seen["LOCALAPPDATA"]


def test_binary_process_preserves_protocol_bytes_and_utf8_input(tmp_path: Path) -> None:
    script = tmp_path / "binary.py"
    script.write_text(
        "import sys\nsys.stdout.buffer.write(sys.stdin.buffer.read())\nsys.stderr.buffer.write(b'error-stream')\n",
        encoding="utf-8",
    )
    argv = (sys.executable, str(script))
    payload = b"record\0\r\n\xfftrailer"
    result = run_binary_process(argv, cwd=tmp_path, input_bytes=payload)
    assert result == ProcessBinaryResult(0, payload, b"error-stream")
    text = "héllo\r\n"
    assert run_input_process(argv, cwd=tmp_path, input_text=text) == ProcessResult(0, text, "error-stream")


def test_binary_process_rejects_actual_failed_execution(tmp_path: Path) -> None:
    script = tmp_path / "failed.py"
    script.write_text("import sys\nsys.stdout.buffer.write(b'valid-looking-output')\nsys.exit(7)\n", encoding="utf-8")
    with pytest.raises(ProcessFailureError) as caught:
        run_binary_process((sys.executable, str(script)), cwd=tmp_path)
    assert caught.value.returncode == 7


def test_binary_result_rejects_text_and_boolean_status() -> None:
    with pytest.raises(TypeError, match="return code must be an integer"):
        ProcessBinaryResult(True)
    with pytest.raises(TypeError, match="binary process output must be bytes"):
        ProcessBinaryResult(0, "text")  # pyright: ignore[reportArgumentType]
