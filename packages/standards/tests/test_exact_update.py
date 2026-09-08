from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

import sarj_standards.cli.main as cli


def _find_uvx(_name: str) -> str:
    return "/opt/uvx"


def test_update_to_bootstraps_the_exact_requested_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.delenv("SARJ_STANDARDS_BOOTSTRAPPED", raising=False)
    monkeypatch.setattr(shutil, "which", _find_uvx)

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "/resolved/bin/python\n")

    monkeypatch.setattr(subprocess, "run", run)

    status = cli.main(["--root", str(tmp_path), "update", "--to", "5.7.1", "--check"])

    assert status == 0
    assert len(observed) == 2
    resolver, resolver_options = observed[0]
    command, update_options = observed[1]
    assert "code-standards==5.7.1" in resolver
    assert resolver[-4:] == ["python", "-I", "-c", "import sys; print(sys.executable)"]
    assert resolver_options["timeout"] == 120
    assert command[:4] == ["/resolved/bin/python", "-I", "-m", "sarj_standards"]
    assert update_options["timeout"] == 1800
    assert command[-3:] == ["--to", "5.7.1", "--check"]
    assert "--offline" not in command
    environment = update_options["env"]
    assert isinstance(environment, dict)
    assert environment["SARJ_STANDARDS_BOOTSTRAPPED"] == "1"


@pytest.mark.parametrize("phase", ["resolution", "execution"])
def test_update_timeout_identifies_the_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], phase: str
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if len(calls) == 1 and phase == "execution":
            return subprocess.CompletedProcess(command, 0, "/resolved/bin/python\n")
        timeout = kwargs["timeout"]
        assert isinstance(timeout, float)
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.delenv("SARJ_STANDARDS_BOOTSTRAPPED", raising=False)
    monkeypatch.setattr(shutil, "which", _find_uvx)
    monkeypatch.setattr(subprocess, "run", run)

    assert cli.main(["--root", str(tmp_path), "update", "--to", "5.7.1"]) == 2
    error = capsys.readouterr().err
    if phase == "resolution":
        assert len(calls) == 1
        assert "resolving the requested standards release timed out" in error
    else:
        assert len(calls) == 2
        assert "update execution exceeded 30 minutes" in error
        assert "check the network" not in error


def test_update_allows_successful_execution_longer_than_resolution_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 0, "/resolved/bin/python\n")
        simulated_elapsed_seconds = 121
        timeout = kwargs["timeout"]
        assert isinstance(timeout, float)
        if simulated_elapsed_seconds > timeout:
            raise subprocess.TimeoutExpired(command, timeout)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.delenv("SARJ_STANDARDS_BOOTSTRAPPED", raising=False)
    monkeypatch.setattr(shutil, "which", _find_uvx)
    monkeypatch.setattr(subprocess, "run", run)

    assert cli.main(["--root", str(tmp_path), "update", "--to", "5.7.1"]) == 0
    assert len(calls) == 2


@pytest.mark.parametrize("exit_code", [1, 2])
def test_update_does_not_execute_after_failed_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_code: int
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, exit_code, "")

    monkeypatch.delenv("SARJ_STANDARDS_BOOTSTRAPPED", raising=False)
    monkeypatch.setattr(shutil, "which", _find_uvx)
    monkeypatch.setattr(subprocess, "run", run)

    assert cli.main(["--root", str(tmp_path), "update", "--to", "5.7.1"]) == exit_code
    assert len(calls) == 1


@pytest.mark.parametrize("resolved_path", ["", "relative/python"])
def test_update_rejects_invalid_resolved_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], resolved_path: str
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, resolved_path)

    monkeypatch.delenv("SARJ_STANDARDS_BOOTSTRAPPED", raising=False)
    monkeypatch.setattr(shutil, "which", _find_uvx)
    monkeypatch.setattr(subprocess, "run", run)

    assert cli.main(["--root", str(tmp_path), "update", "--to", "5.7.1"]) == 2
    assert len(calls) == 1
    assert "absolute Python interpreter path" in capsys.readouterr().err


@pytest.mark.parametrize("exit_code", [1, 2])
def test_update_preserves_resolved_execution_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], exit_code: int
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if len(calls) == 1:
            return subprocess.CompletedProcess(command, 0, "/resolved/bin/python\n")
        return subprocess.CompletedProcess(command, exit_code)

    monkeypatch.delenv("SARJ_STANDARDS_BOOTSTRAPPED", raising=False)
    monkeypatch.setattr(shutil, "which", _find_uvx)
    monkeypatch.setattr(subprocess, "run", run)

    assert cli.main(["--root", str(tmp_path), "update", "--to", "5.7.1"]) == exit_code
    assert len(calls) == 2
    assert not capsys.readouterr().err


@pytest.mark.parametrize("no_cache", ["1", "true", "TRUE", "yes", "on"])
@pytest.mark.parametrize("execution_status", [0, 2])
def test_no_cache_update_keeps_interpreter_until_execution_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_cache: str, execution_status: int
) -> None:
    calls: list[list[str]] = []
    cache_paths: list[Path] = []
    persistent_cache = tmp_path / "persistent-cache"

    def run(command: list[str], *, env: dict[str, str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        if len(calls) == 1:
            assert "UV_NO_CACHE" not in env
            cache_path = Path(env["UV_CACHE_DIR"])
            cache_paths.append(cache_path)
            assert cache_path.is_dir()
            interpreter = cache_path / "python"
            interpreter.touch()
            return subprocess.CompletedProcess(command, 0, f"{interpreter}\n")
        assert Path(command[0]).is_file()
        assert env["UV_NO_CACHE"] == no_cache
        assert env["UV_CACHE_DIR"] == str(persistent_cache)
        return subprocess.CompletedProcess(command, execution_status)

    monkeypatch.delenv("SARJ_STANDARDS_BOOTSTRAPPED", raising=False)
    monkeypatch.setenv("UV_NO_CACHE", no_cache)
    monkeypatch.setenv("UV_CACHE_DIR", str(persistent_cache))
    monkeypatch.setattr(shutil, "which", _find_uvx)
    monkeypatch.setattr(subprocess, "run", run)

    assert cli.main(["--root", str(tmp_path), "update", "--to", "5.7.1"]) == execution_status
    assert len(calls) == 2
    assert not cache_paths[0].exists()
    assert not persistent_cache.exists()


@pytest.mark.parametrize("no_cache", ["0", "false", "FALSE", "no", "off", "invalid"])
def test_update_preserves_disabled_or_invalid_no_cache_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_cache: str
) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], *, env: dict[str, str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert env["UV_NO_CACHE"] == no_cache
        assert env["UV_CACHE_DIR"] == str(tmp_path)
        return subprocess.CompletedProcess(command, 0, "/resolved/bin/python\n")

    monkeypatch.delenv("SARJ_STANDARDS_BOOTSTRAPPED", raising=False)
    monkeypatch.setenv("UV_NO_CACHE", no_cache)
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(shutil, "which", _find_uvx)
    monkeypatch.setattr(subprocess, "run", run)

    assert cli.main(["--root", str(tmp_path), "update", "--to", "5.7.1"]) == 0
    assert len(calls) == 2


def test_exact_inner_update_rejects_an_executing_version_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SARJ_STANDARDS_BOOTSTRAPPED", "1")

    status = cli.main(["--root", str(tmp_path), "update", "--to", "999.0.0"])

    assert status == 2
    assert "executing bundle is" in capsys.readouterr().err


def test_exact_update_rejects_noncanonical_versions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = cli.main(["--root", str(tmp_path), "update", "--to", "05.07.01"])

    assert status == 2
    assert "must be canonical" in capsys.readouterr().err
