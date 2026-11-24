from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from sarj_standards.libs.adoption import manifest
from sarj_standards.libs.linting.devops_tools import MISE_REFS, TOOLS
from sarj_standards.libs.release import native_test_setup


_SERVICE_INSTALLER = Path(__file__).resolve().parents[4] / ".github/scripts/setup-native-config-tests.sh"
_APT_FIXTURE = r"""
import hashlib
import os
from pathlib import Path
import sys

root = Path(os.environ["NATIVE_FIXTURE"])
case = os.environ["NATIVE_CASE"]
name = Path(sys.argv[0]).name
args = sys.argv[1:]
snapshot = "APT_CONFIG" in os.environ
packages = ("nginx=1.24.0-2ubuntu7.21", "kamailio=5.7.4-1build7", "prometheus=2.45.3+ds-2ubuntu0.3")
with (root / "events").open("a") as stream:
    stream.write(f"{name} {'snapshot' if snapshot else 'rolling'} {' '.join(args)}\n")
if name == "dpkg-deb":
    assert args[0] == "--extract"
    Path(args[2]).mkdir(parents=True, exist_ok=True)
    raise SystemExit(0)
if args[-1] == "update":
    config = Path(os.environ["APT_CONFIG"])
    (root / "snapshot-config").write_text(config.read_text())
    (root / "snapshot-sources").write_text((config.parent / "ubuntu.sources").read_text())
    (root / "snapshot-path").write_text(str(config.parent))
    assert config.parent.is_relative_to(root / "archives")
    assert (config.parent / "lists/partial").is_dir()
    assert (config.parent / "cache").is_dir()
    raise SystemExit(100 if case == "update-failure" else 0)
if args[:2] == ["--print-uris", "download"]:
    assert tuple(args[2:]) == packages
    if not snapshot and case != "rolling":
        raise SystemExit(100)
    if case == "snapshot-missing":
        raise SystemExit(100)
    for index, package in enumerate(packages):
        if case == "incomplete" and index == 2:
            continue
        archive = package.split("=")[0] + ".deb"
        payload = package.encode()
        checksum = "SHA512:" + hashlib.sha512(payload).hexdigest()
        if case == "weak":
            checksum = "MD5Sum:" + "0" * 32
        if case == "unsafe":
            archive = "../" + archive
        print(f"'https://fixture.invalid/{archive}' {archive} {len(payload)} {checksum}")
    raise SystemExit(0)
assert args[0] == "-o" and "download" in args
assert tuple(args[args.index("download") + 1:]) == packages
counter = root / "downloads"
attempt = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(attempt))
if case == "download-failure" or (case == "retry" and attempt == 1):
    raise SystemExit(23)
for package in packages:
    archive = Path(package.split("=")[0] + ".deb")
    if not archive.exists():
        with (root / "fetches").open("a") as stream:
            stream.write(archive.name + "\n")
        archive.write_bytes(package.encode())
"""


@pytest.fixture
def native_service_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    if shutil.which("bash") is None or not Path("/usr/lib/apt/apt-helper").is_file():
        pytest.skip("Native service archive checks require Bash and APT's checksum helper")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("apt-get", "dpkg-deb"):
        executable = binaries / name
        executable.write_text(f"#!{sys.executable}\n{_APT_FIXTURE}")
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries), prepend=os.pathsep)
    monkeypatch.setenv("NATIVE_FIXTURE", str(tmp_path))
    monkeypatch.setenv("GITHUB_PATH", str(tmp_path / "github-path"))
    monkeypatch.delenv("APT_CONFIG", raising=False)
    return tmp_path


@pytest.mark.parametrize("case", ["rolling", "fallback", "retry", "cached", "corrupt-cache"])
def test_native_services_preserve_exact_pins_and_verified_bytes(
    native_service_fixture: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    root = native_service_fixture
    archives = root / "archives"
    archives.mkdir()
    if case in {"cached", "corrupt-cache"}:
        for package in (
            "nginx=1.24.0-2ubuntu7.21",
            "kamailio=5.7.4-1build7",
            "prometheus=2.45.3+ds-2ubuntu0.3",
        ):
            payload = b"corrupt" if case == "corrupt-cache" else package.encode()
            (archives / (package.split("=")[0] + ".deb")).write_bytes(payload)
    monkeypatch.setenv("NATIVE_CASE", case)
    result = subprocess.run(
        ("bash", str(_SERVICE_INSTALLER), str(archives)), check=False, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    events = (root / "events").read_text().splitlines()
    assert sum(event.startswith("dpkg-deb ") for event in events) == 3
    assert (root / "downloads").read_text() == ("2" if case == "retry" else "1")
    fetches = (root / "fetches").read_text().splitlines() if (root / "fetches").exists() else []
    assert len(fetches) == (0 if case == "cached" else 3)
    assert (root / "github-path").read_text().splitlines() == [
        str(archives / "root/usr/sbin"),
        str(archives / "root/usr/bin"),
    ]
    assert not list(archives.glob(".native-packages.*"))
    if case == "rolling":
        assert not (root / "snapshot-config").exists()
    else:
        sources = (root / "snapshot-sources").read_text()
        assert "URIs: https://snapshot.ubuntu.com/ubuntu/20261124T000000Z/" in sources
        assert "Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg" in sources
        assert "Suites: noble noble-updates noble-security" in sources
        assert not Path((root / "snapshot-path").read_text()).exists()


@pytest.mark.parametrize(
    ("case", "status", "downloads"),
    [
        ("update-failure", 100, 0),
        ("snapshot-missing", 100, 0),
        ("weak", 1, 0),
        ("incomplete", 1, 0),
        ("unsafe", 1, 0),
        ("download-failure", 23, 2),
    ],
)
def test_native_services_fail_closed_before_extracting_or_exporting_paths(
    native_service_fixture: Path, monkeypatch: pytest.MonkeyPatch, case: str, status: int, downloads: int
) -> None:
    root = native_service_fixture
    monkeypatch.setenv("NATIVE_CASE", case)
    result = subprocess.run(
        ("bash", str(_SERVICE_INSTALLER), str(root / "archives")),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == status, result.stderr
    assert not (root / "github-path").exists()
    assert not (root / "archives/root").exists()
    attempts = int((root / "downloads").read_text()) if (root / "downloads").exists() else 0
    assert attempts == downloads
    assert not list((root / "archives").glob(".native-packages.*"))


@pytest.mark.parametrize("failing_tool", ["mise", "uvx"])
def test_integration_installer_failure_preserves_consumer_optouts_and_stops_before_path_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_tool: str
) -> None:
    workflow = tmp_path / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "name: Test\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo fixture\n"
    )
    adopted = manifest.Manifest(version=manifest.adopted_version(), configs=(), python_dest=".", typescript_dest=".")
    configuration = tmp_path / manifest.MANIFEST_NAME
    configuration.write_text(adopted.render())
    original = configuration.read_bytes()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for tool in ("mise", "uvx"):
        executable = binaries / tool
        executable.write_text(
            f"#!{sys.executable}\n"
            "import json, sys\n"
            "from pathlib import Path\n"
            f"Path({str(tmp_path / (tool + '.json'))!r}).write_text(json.dumps(sys.argv[1:]))\n"
            f"sys.exit({7 if tool == failing_tool else 0})\n"
        )
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries))
    output = tmp_path / "github-path"
    monkeypatch.setenv("GITHUB_PATH", str(output))
    assert native_test_setup.setup(tmp_path) == 7
    command: object = json.loads((tmp_path / "mise.json").read_text())  # pyright: ignore[reportAny] -- JSON command recording boundary.
    required = ("actionlint", "helm", "knip", "kube-linter", "kubeconform", "shellcheck", "shfmt")
    assert command == [
        "--no-config",
        "--no-env",
        "--no-hooks",
        "install",
        *(f"{MISE_REFS[name]}@{TOOLS[name].version}" for name in required),
    ]
    security_install = tmp_path / "uvx.json"
    if failing_tool == "uvx":
        security_command: object = json.loads(security_install.read_text())  # pyright: ignore[reportAny] -- JSON command recording boundary.
        assert security_command == [
            "--no-config",
            "--isolated",
            "--python",
            "3.12",
            "--from",
            "zizmor==1.33.1",
            "zizmor",
            "--version",
        ]
    else:
        assert not security_install.exists()
    assert configuration.read_bytes() == original
    assert not output.exists()
