from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("sha256sum") is None,
    reason="Ubuntu archive setup requires Bash and sha256sum",
)
SCRIPT = Path(__file__).resolve().parents[4] / ".github/scripts/setup-native-config-tests.sh"
ARCHIVES = (
    "nginx_1.24.0-2ubuntu7.18_amd64.deb",
    "kamailio_5.7.4-1build7_amd64.deb",
    "prometheus_2.45.3+ds-2ubuntu0.3_amd64.deb",
)


@pytest.fixture
def archive_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    program = (
        f"#!{sys.executable}\n"
        """\
from pathlib import Path
import hashlib, os, sys
tool = Path(sys.argv[0]).name
if tool == 'dpkg':
    print('amd64')
elif tool == 'apt-cache':
    package = sys.argv[2].split(':')[0]
    if not os.environ.get('EMPTY_ARCHIVE_METADATA'):
        print('SHA256: ' + hashlib.sha256(package.encode()).hexdigest())
elif tool == 'apt-get':
    assert sys.argv[1] == 'download'
    for specification in sys.argv[2:]:
        package = specification.split('=')[0]
        archive = Path(specification.replace('=', '_') + '_amd64.deb')
        payload = package.encode()
        # Reproduce APT's size-only acceptance of an existing archive.
        if not archive.exists() or archive.stat().st_size != len(payload):
            archive.write_bytes(payload)
            with Path('downloads').open('a') as stream:
                stream.write(archive.name + '\\n')
elif tool == 'dpkg-deb':
    assert sys.argv[1] == '--extract'
    with Path('extracted').open('a') as stream:
        stream.write(sys.argv[2] + '\\n')
else:
    raise AssertionError(tool)
"""
    )
    for name in ("apt-get", "apt-cache", "dpkg", "dpkg-deb"):
        executable = binaries / name
        executable.write_text(program)
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(binaries), prepend=os.pathsep)
    monkeypatch.setenv("GITHUB_PATH", str(tmp_path / "github-path"))
    cache = tmp_path / "archives"
    cache.mkdir()
    return cache


@pytest.mark.parametrize(("state", "download_count"), [("cold", 3), ("warm", 0), ("corrupt", 1)])
def test_pinned_archives_reuse_verified_bytes_and_recover_same_size_corruption(
    archive_tools: Path, state: str, download_count: int
) -> None:
    if state != "cold":
        for archive in ARCHIVES:
            (archive_tools / archive).write_bytes(archive.split("_")[0].encode())
    if state == "corrupt":
        (archive_tools / ARCHIVES[0]).write_bytes(b"XXXXX")
    unrelated = archive_tools / "unrequested.deb"
    unrelated.write_bytes(b"must not be extracted")
    subprocess.run(["bash", str(SCRIPT), str(archive_tools)], check=True, capture_output=True, text=True)
    downloaded = archive_tools / "downloads"
    actual_download_count = len(downloaded.read_text().splitlines()) if downloaded.exists() else 0
    assert actual_download_count == download_count
    assert (archive_tools / "extracted").read_text().splitlines() == list(ARCHIVES)
    assert unrelated.read_bytes() == b"must not be extracted"
    assert (archive_tools / ARCHIVES[0]).read_bytes() == b"nginx"


def test_missing_repository_digest_stops_before_download_extraction_or_path_export(
    archive_tools: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EMPTY_ARCHIVE_METADATA", "1")
    result = subprocess.run(["bash", str(SCRIPT), str(archive_tools)], check=False, capture_output=True, text=True)
    assert result.returncode != 0
    assert "Expected one repository SHA256" in result.stderr
    assert not (archive_tools / "downloads").exists()
    assert not (archive_tools / "extracted").exists()
    assert not (archive_tools.parent / "github-path").exists()
