from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption import doctor, manifest
from sarj_standards.libs.linting import devops_tools
from sarj_standards.libs.linting.devops_tools import (
    TOOLS,
    NativeTool,
    NativeToolError,
    NativeToolMissingError,
    checked_tool,
)
from sarj_standards.libs.linting.external import ProcessOutput, run_process


if TYPE_CHECKING:
    from collections.abc import Sequence

    from sarj_standards.libs.linting.external import ProcessRunner


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        pytest.param("version: 0.11.0-beta", 0, id="prerelease"),
        pytest.param("version: 0.11.0 extra", 0, id="trailing-data"),
        pytest.param("version: 0.11.00", 0, id="wrong-version"),
        pytest.param("version: 0.11.0\nversion: 0.11.0", 0, id="duplicate-versions"),
        pytest.param("version:\n0.11.0", 0, id="split-line"),
        pytest.param("version: 0.11.0", 1, id="failed-process"),
        pytest.param("", 0, id="missing-version"),
    ],
)
def test_shellcheck_rejects_nonexact_version_protocol(*, tmp_path: Path, payload: str, status: int) -> None:
    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert tuple(argv) == ("shellcheck", "--version")
        assert cwd == tmp_path
        return ProcessOutput(status, payload, "")

    with pytest.raises(NativeToolError, match="exact version"):
        checked_tool("shellcheck", root=tmp_path, runner=runner)


@pytest.mark.parametrize(
    "payload",
    [
        "version: 0.11.0",
        "ShellCheck\nversion: 0.11.0\nlicense: GNU",
        "version:  0.11.0\t",
        "ShellCheck\r\nversion: 0.11.0\r\nlicense: GNU\r\n",
    ],
)
def test_shellcheck_accepts_exact_version_line(*, tmp_path: Path, payload: str) -> None:
    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        assert tuple(argv) == ("shellcheck", "--version")
        return ProcessOutput(0, payload, "")

    assert checked_tool("shellcheck", root=tmp_path, runner=runner).version == "0.11.0"


def test_tflint_core_version_uses_packaged_config_with_injected_runner(*, tmp_path: Path) -> None:
    def runner(argv: Sequence[str], *, cwd: Path) -> ProcessOutput:
        assert cwd == tmp_path
        assert tuple(argv[:3]) == ("tflint", "--version", "--config")
        prefix, version_flag, config_flag, config_path = argv
        assert (prefix, version_flag, config_flag) == ("tflint", "--version", "--config")
        config = Path(config_path)
        assert config.is_absolute()
        assert config.is_file()
        assert not config.is_relative_to(tmp_path)
        return ProcessOutput(0, "TFLint version 0.63.1", "")

    assert checked_tool("tflint", root=tmp_path, runner=runner).version == "0.63.1"


@pytest.mark.parametrize("state", ["missing", "wrong-version", "deadline", "valid"])
def test_doctor_preserves_native_finding_identity(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    adopted = manifest.Manifest(manifest.adopted_version(), ("shellcheck",), ".", ".")
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    shell = tmp_path / "fixture.sh"
    shell.write_text("#!/bin/sh\nprintf fixture\n", encoding="utf-8")
    calls: list[str] = []

    def attest(
        name: str, *, root: Path, runner: ProcessRunner | None = None, expected_version: str | None = None
    ) -> NativeTool:
        assert root == tmp_path
        assert runner is None or name != "shellcheck"
        assert expected_version is None
        calls.append(name)
        if name == "shellcheck":
            if state == "missing":
                message = "not installed"
                raise NativeToolMissingError(message)
            if state == "wrong-version":
                message = "nonexact version"
                raise NativeToolError(message)
            if state == "deadline":
                raise subprocess.TimeoutExpired(("shellcheck", "--version"), 5)
        return TOOLS[name]

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- intercept canonical native attestation; injecting doctor findings would bypass the public doctor health boundary under test.
        devops_tools, "checked_tool", attest
    )
    findings = [
        finding for finding in doctor.diagnose_adoption_health(tmp_path, (shell,)) if finding.where == "shellcheck"
    ]
    assert calls.count("shellcheck") == 1
    assert len(findings) == 1
    assert findings[0].id == ("doctor.shellcheck.missing" if state == "missing" else "doctor.shellcheck.version")
    assert findings[0].level is (doctor.Level.OK if state == "valid" else doctor.Level.DRIFT)


@pytest.mark.parametrize("payload", [None, "version: 0.10.0", "version: 0.11.0"])
def test_canonical_discovery_keeps_missing_and_invalid_distinct(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str | None
) -> None:
    executable = tmp_path / "native-shellcheck"
    executable.write_text("fixture executable", encoding="utf-8")
    calls: list[tuple[tuple[str, ...], float]] = []

    def resolve(name: str, *, path: str | None = None) -> str | None:
        assert name in {"shellcheck", "mise"}
        assert path is None or path == str(Path(sys.executable).parent)
        return str(executable) if name == "shellcheck" and payload is not None else None

    def runner(argv: Sequence[str], *, cwd: Path, timeout_seconds: float = 900) -> ProcessOutput:
        assert cwd == tmp_path
        assert argv[0] == str(executable)
        calls.append((tuple(argv), timeout_seconds))
        assert payload is not None
        return ProcessOutput(0, payload, "")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- replace process-global executable discovery while exercising the canonical public resolver's production path.
        shutil, "which", resolve
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe production runner identity and deadline; a protocol-injected runner bypasses executable discovery by contract.
        devops_tools, "run_process", runner
    )
    if payload is None:
        with pytest.raises(NativeToolMissingError):
            checked_tool("shellcheck", root=tmp_path, runner=runner)
        assert not calls
    elif payload != "version: 0.11.0":
        with pytest.raises(NativeToolError, match="exact version") as error:
            checked_tool("shellcheck", root=tmp_path, runner=runner)
        assert not isinstance(error.value, NativeToolMissingError)
        assert calls
        assert calls == [((str(executable), "--version"), 5)]
    else:
        tool = checked_tool("shellcheck", root=tmp_path, runner=runner)
        assert tool.executable == executable
        assert calls == [((str(executable), "--version"), 5)]


def test_native_process_deadline_is_optional_and_bounded(*, tmp_path: Path) -> None:
    probe = tmp_path / "delay.py"
    probe.write_text("import time\ntime.sleep(1)\n", encoding="utf-8")
    with pytest.raises(subprocess.TimeoutExpired):
        run_process((sys.executable, str(probe)), cwd=tmp_path, timeout_seconds=0.05)
    probe.write_text("print('fixture')\n", encoding="utf-8")
    output = run_process((sys.executable, str(probe)), cwd=tmp_path)
    assert output.returncode == 0
    assert output.stdout == "fixture\n"


@pytest.mark.skipif(sys.platform == "win32", reason="Native shell marker control requires a POSIX executable fixture")
def test_actual_tflint_core_version_never_starts_project_plugins(*, tmp_path: Path) -> None:
    try:
        tool = checked_tool("tflint", root=tmp_path)
    except NativeToolMissingError:
        pytest.skip("optional actual pinned TFLint 0.63.1 is not installed in this test environment")
    assert tool.version == "0.63.1"
    (tmp_path / ".tflint.hcl").write_text('plugin "probe" {\n enabled = true\n}\n', encoding="utf-8")
    for name in ("probe", "terraform"):
        plugin = tmp_path / f".tflint.d/plugins/tflint-ruleset-{name}"
        plugin.parent.mkdir(parents=True, exist_ok=True)
        plugin.write_text(f"#!/bin/sh\nprintf invoked > {name}-invoked\nexit 1\n", encoding="utf-8")
        plugin.chmod(0o700)
    assert checked_tool("tflint", root=tmp_path).executable == tool.executable
    assert not any((tmp_path / f"{name}-invoked").exists() for name in ("probe", "terraform"))


@pytest.mark.parametrize(
    ("configs", "name", "source"),
    [
        pytest.param(("shellcheck",), "fixture.zsh", "#!/bin/zsh\nprintf fixture\n", id="unsupported-zsh"),
        pytest.param(("shellcheck",), "fixture.py", "print('fixture')\n", id="nonshell-input"),
        pytest.param((), "fixture.sh", "#!/bin/sh\nprintf fixture\n", id="capability-optout"),
    ],
)
def test_doctor_only_attests_eligible_adopted_shell(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configs: tuple[str, ...], name: str, source: str
) -> None:
    adopted = manifest.Manifest(manifest.adopted_version(), configs, ".", ".")
    (tmp_path / manifest.MANIFEST_NAME).write_text(adopted.render(), encoding="utf-8")
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")

    def attest(
        name: str, *, root: Path, runner: ProcessRunner | None = None, expected_version: str | None = None
    ) -> NativeTool:
        assert root == tmp_path
        assert runner is not None or name != "shellcheck"
        assert expected_version is None
        assert name != "shellcheck"
        return TOOLS[name]

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- observe native selection through public doctor health; fixture input must not acquire an unrelated ShellCheck requirement.
        devops_tools, "checked_tool", attest
    )
    assert not any(finding.where == "shellcheck" for finding in doctor.diagnose_adoption_health(tmp_path, (path,)))
