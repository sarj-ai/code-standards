from __future__ import annotations

import hashlib
import io
from pathlib import Path
import platform
import shlex
import stat
from typing import TYPE_CHECKING
from urllib.error import URLError


if TYPE_CHECKING:
    from urllib.request import Request

import pytest
import yaml

from sarj_standards.libs.adoption import launcher, manifest, native_bootstrap, scaffold
from sarj_standards.libs.typed_containers import is_object_list, is_object_mapping


_PAYLOAD = b"verified mise fixture"
_DIGEST = hashlib.sha256(_PAYLOAD).hexdigest()
_REPOSITORY = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("system", "architecture", "target"),
    [
        ("Linux", "x86_64", "linux-x64"),
        ("Linux", "aarch64", "linux-arm64"),
        ("Darwin", "x86_64", "macos-x64"),
        ("Darwin", "arm64", "macos-arm64"),
    ],
)
@pytest.mark.parametrize("cached", [None, _PAYLOAD, b"tampered"])
def test_bootstrap_verifies_download_and_every_cache_hit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    system: str,
    architecture: str,
    target: str,
    cached: bytes | None,
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test bootstrap lookup; caller overrides would allow unpinned artifacts.
        platform, "system", lambda: system
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test bootstrap lookup; caller overrides would allow unpinned artifacts.
        platform, "machine", lambda: architecture
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test bootstrap lookup; caller overrides would allow unpinned artifacts.
        native_bootstrap, "_DIGESTS", {target: _DIGEST}
    )
    calls: list[str] = []

    def download(request: Request, *, timeout: int) -> io.BytesIO:
        assert timeout == 120
        calls.append(request.full_url)
        return io.BytesIO(_PAYLOAD)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test bootstrap lookup; caller overrides would allow unpinned artifacts.
        native_bootstrap, "urlopen", download
    )
    destination = tmp_path / native_bootstrap.VERSION / target / "bin/mise"
    if cached is not None:
        destination.parent.mkdir(parents=True)
        destination.write_bytes(cached)
    executable = native_bootstrap.provision(tmp_path)
    assert executable == destination.resolve()
    assert executable.read_bytes() == _PAYLOAD
    assert executable.stat().st_mode & stat.S_IXUSR
    assert calls == (
        []
        if cached == _PAYLOAD
        else [
            f"https://github.com/jdx/mise/releases/download/v{native_bootstrap.VERSION}/mise-v{native_bootstrap.VERSION}-{target}"
        ]
    )
    assert list(destination.parent.iterdir()) == [destination]


@pytest.mark.parametrize("failure", ["checksum", "network"])
def test_failed_bootstrap_does_not_publish_corrupt_cache_or_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test bootstrap lookup; caller overrides would allow unpinned artifacts.
        platform, "system", lambda: "Linux"
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test bootstrap lookup; caller overrides would allow unpinned artifacts.
        platform, "machine", lambda: "x86_64"
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test bootstrap lookup; caller overrides would allow unpinned artifacts.
        native_bootstrap, "_DIGESTS", {"linux-x64": _DIGEST}
    )
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    path_file = tmp_path / "github-path"
    path_file.write_text("previous-path\n")
    monkeypatch.setenv("GITHUB_PATH", str(path_file))
    destination = tmp_path / "code-standards/native-bootstrap" / native_bootstrap.VERSION / "linux-x64/bin/mise"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"previous corrupt cache")

    def download(_request: Request, *, timeout: int) -> io.BytesIO:
        assert timeout == 120
        if failure == "network":
            message = "download failed"
            raise URLError(message)
        return io.BytesIO(b"bad checksum")

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test bootstrap lookup; caller overrides would allow unpinned artifacts.
        native_bootstrap, "urlopen", download
    )
    with pytest.raises(OSError, match=r"download failed|checksum mismatch"):
        native_bootstrap.main()
    assert destination.read_bytes() == b"previous corrupt cache"
    assert path_file.read_text() == "previous-path\n"
    assert list(destination.parent.iterdir()) == [destination]


def test_bootstrap_exports_only_verified_binary_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test bootstrap lookup; caller overrides would allow unpinned artifacts.
        platform, "system", lambda: "Linux"
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test bootstrap lookup; caller overrides would allow unpinned artifacts.
        platform, "machine", lambda: "x86_64"
    )
    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- test bootstrap lookup; caller overrides would allow unpinned artifacts.
        native_bootstrap, "_DIGESTS", {"linux-x64": _DIGEST}
    )
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    path_file = tmp_path / "github-path"
    monkeypatch.setenv("GITHUB_PATH", str(path_file))
    destination = tmp_path / "code-standards/native-bootstrap" / native_bootstrap.VERSION / "linux-x64/bin/mise"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(_PAYLOAD)
    native_bootstrap.main()
    assert path_file.read_text() == f"{destination.parent.resolve()}\n"
    assert not (destination.parent / "shims").exists()


def test_root_and_generated_ci_bootstrap_before_tools_setup(tmp_path: Path) -> None:
    workflows = [(_REPOSITORY / ".github/workflows/ci.yml").read_text(), scaffold.github_ci_workflow(tmp_path)]
    commands: list[list[str]] = []
    for workflow in workflows:
        document: object = yaml.safe_load(workflow)  # pyright: ignore[reportAny] -- narrow workflow configuration at the YAML boundary.
        assert is_object_mapping(document)
        jobs = document["jobs"]
        assert is_object_mapping(jobs)
        for job in jobs.values():
            assert is_object_mapping(job)
            steps = job["steps"]
            assert is_object_list(steps)
            bootstrap: int | None = None
            for index, step in enumerate(steps):
                assert is_object_mapping(step)
                if step.get("name") == "Install the pinned native tool bootstrap":
                    assert "uses" not in step
                    run = step["run"]
                    assert isinstance(run, str)
                    argv = shlex.split(run)
                    if "--no-config" in argv:
                        assert step["env"] == {"UV_PYTHON_DOWNLOADS_JSON_URL": launcher.PYTHON_DOWNLOADS}
                    assert argv[-3:] == ["python", "-m", "sarj_standards.libs.adoption.native_bootstrap"]
                    commands.append(argv)
                    bootstrap = index
                if step.get("name") in {
                    "Install and attest applicable native tools",
                    "Install and attest integration native tools",
                }:
                    assert bootstrap is not None
                    assert bootstrap < index
    assert commands
    assert commands[-1] == [
        "uv",
        "run",
        "--no-config",
        "--no-project",
        "--python",
        "3.15.0",
        "--with",
        f"code-standards=={manifest.adopted_version()}",
        "python",
        "-m",
        "sarj_standards.libs.adoption.native_bootstrap",
    ]
