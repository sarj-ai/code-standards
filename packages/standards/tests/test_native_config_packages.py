from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess
import sys

import pytest


_SCRIPT = Path(__file__).resolve().parents[3] / ".github/scripts/setup-native-config-tests.sh"
_TOOLS = """\
import hashlib
import os
from pathlib import Path
import shlex
import sys

root = Path(os.environ['PACKAGE_FIXTURE_ROOT'])
mode = os.environ['PACKAGE_FIXTURE_MODE']
tool = Path(sys.argv[0]).name
arguments = sys.argv[1:]
with (root / 'events').open('a', encoding='utf-8') as stream:
    stream.write(shlex.join([tool, *arguments]) + '\\n')
content = b'private native package fixture'
archives = ('nginx.deb', 'kamailio.deb', 'prometheus.deb')
if tool == 'sudo':
    assert arguments[:4] == ['-n', 'timeout', '120s', 'apt-get']
    os.execvp(arguments[1], arguments[1:])
elif tool == 'apt-cache':
    assert arguments == ['policy', 'nginx', 'kamailio', 'prometheus']
    print('nginx: Candidate: fixture-old-index')
    print(
        '  500 https://fixture-user:fixture-password@example.invalid/private-index '
        'noble-security/main amd64 Packages'
    )
elif tool == 'dpkg-deb':
    assert arguments[0] == '--extract'
    assert Path(arguments[1]).read_bytes() == content
    Path(arguments[2]).mkdir(parents=True, exist_ok=True)
elif tool == 'apt-get':
    if arguments[-1] == 'update':
        assert 'Acquire::Retries=0' in arguments
        assert 'Acquire::http::Timeout=15' in arguments
        assert 'Acquire::https::Timeout=15' in arguments
        assert 'APT::Update::Error-Mode=any' in arguments
        if mode == 'update-fails':
            raise SystemExit(42)
        (root / 'refreshed').touch()
    else:
        assert arguments[-3:] == [
            'nginx=1.24.0-2ubuntu7.19',
            'kamailio=5.7.4-1build7',
            'prometheus=2.45.3+ds-2ubuntu0.3',
        ]
        if '--print-uris' in arguments:
            if mode == 'query-error':
                raise SystemExit(73)
            if mode == 'still-missing' or (mode in {'missing', 'update-fails'} and not (root / 'refreshed').exists()):
                raise SystemExit(100)
            checksum = 'SHA256:' + hashlib.sha256(content).hexdigest()
            if mode == 'weak-checksum':
                checksum = 'MD5Sum:' + '0' * 32
            for archive in archives:
                print(f"'https://example.invalid/{archive}' {archive} {len(content)} {checksum}")
        elif mode == 'download-fails':
            raise SystemExit(21)
        else:
            for archive in archives:
                Path(archive).write_bytes(content)
else:
    raise SystemExit('unexpected fixture executable')
"""


@dataclass(frozen=True)
class _PackageSetup:
    root: Path
    tools: Path

    def run(
        self, mode: str, *, github_actions: str = "", runner_environment: str = ""
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("bash", str(_SCRIPT), str(self.root / "native cache")),
            cwd=self.root,
            env={
                "PATH": f"{self.tools}:/usr/bin:/bin",
                "PACKAGE_FIXTURE_ROOT": str(self.root),
                "PACKAGE_FIXTURE_MODE": mode,
                "GITHUB_PATH": str(self.root / "native-paths"),
                "GITHUB_ACTIONS": github_actions,
                "RUNNER_ENVIRONMENT": runner_environment,
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    def calls(self, tool: str) -> list[list[str]]:
        return [
            arguments[1:]
            for line in (self.root / "events").read_text(encoding="utf-8").splitlines()
            if (arguments := shlex.split(line))[0] == tool
        ]


@pytest.fixture
def package_setup(tmp_path: Path) -> _PackageSetup:
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("apt-get", "apt-cache", "sudo", "dpkg-deb"):
        executable = tools / name
        executable.write_text(f"#!{sys.executable}\n{_TOOLS}", encoding="utf-8")
        executable.chmod(0o755)
    return _PackageSetup(tmp_path, tools)


@pytest.mark.parametrize(
    "runner_environment",
    [
        pytest.param("", id="local"),
        pytest.param("self-hosted", id="self-hosted"),
        pytest.param("github-hosted", id="github-hosted"),
    ],
)
def test_available_native_package_metadata_skips_refresh(package_setup: _PackageSetup, runner_environment: str) -> None:
    result = package_setup.run("available", github_actions="true", runner_environment=runner_environment)

    assert result.returncode == 0, result.stderr
    assert not package_setup.calls("sudo")
    assert not package_setup.calls("apt-cache")
    assert len(package_setup.calls("apt-get")) == 2
    assert len(package_setup.calls("dpkg-deb")) == 3


@pytest.mark.parametrize(
    ("github_actions", "runner_environment"),
    [
        pytest.param("", "", id="local"),
        pytest.param("true", "self-hosted", id="self-hosted"),
        pytest.param("", "github-hosted", id="missing-actions-context"),
        pytest.param("false", "github-hosted", id="false-actions-context"),
        pytest.param("true", "", id="missing-runner-context"),
    ],
)
@pytest.mark.parametrize(
    ("mode", "status"),
    [pytest.param("missing", 100, id="missing-pin"), pytest.param("query-error", 73, id="other-query-failure")],
)
def test_native_metadata_failure_does_not_refresh_shared_hosts(
    package_setup: _PackageSetup, github_actions: str, runner_environment: str, mode: str, status: int
) -> None:
    result = package_setup.run(mode, github_actions=github_actions, runner_environment=runner_environment)

    assert result.returncode == status
    assert not package_setup.calls("sudo")
    assert len(package_setup.calls("apt-get")) == 1
    assert not package_setup.calls("dpkg-deb")


def test_hosted_native_metadata_refresh_retries_the_exact_pins(package_setup: _PackageSetup) -> None:
    result = package_setup.run("missing", github_actions="true", runner_environment="github-hosted")

    assert result.returncode == 0, result.stderr
    calls = package_setup.calls("apt-get")
    assert len(calls) == 4
    assert calls[0] == calls[2]
    assert calls[1][-1] == "update"
    assert len(package_setup.calls("sudo")) == 1
    assert len(package_setup.calls("apt-cache")) == 1
    assert "noble-security/main amd64 Packages" in result.stdout
    assert "[package-index]" in result.stdout
    assert "fixture-password" not in result.stdout
    assert "private-index" not in result.stdout
    assert len(package_setup.calls("dpkg-deb")) == 3
    assert not list((package_setup.root / "native cache").glob(".native-packages.*"))


@pytest.mark.parametrize(
    ("mode", "status"),
    [pytest.param("update-fails", 42, id="update-failure"), pytest.param("still-missing", 100, id="pin-unavailable")],
)
def test_hosted_native_refresh_failure_remains_fatal(package_setup: _PackageSetup, mode: str, status: int) -> None:
    result = package_setup.run(mode, github_actions="true", runner_environment="github-hosted")

    assert result.returncode == status
    assert len(package_setup.calls("sudo")) == 1
    assert not package_setup.calls("dpkg-deb")
    assert not list((package_setup.root / "native cache").glob("*.deb"))


@pytest.mark.parametrize(
    ("mode", "status"),
    [pytest.param("weak-checksum", 1, id="weak-metadata"), pytest.param("download-fails", 21, id="retrieval-failure")],
)
def test_native_package_validation_and_download_failures_do_not_refresh(
    package_setup: _PackageSetup, mode: str, status: int
) -> None:
    result = package_setup.run(mode, github_actions="true", runner_environment="github-hosted")

    assert result.returncode == status
    assert not package_setup.calls("sudo")
    assert not package_setup.calls("dpkg-deb")
    expected_calls = 3 if mode == "download-fails" else 1
    assert len(package_setup.calls("apt-get")) == expected_calls
