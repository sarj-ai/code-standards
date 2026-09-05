from __future__ import annotations

from email.message import Message
import importlib.util
from pathlib import Path
import subprocess
import sys
from typing import NamedTuple, Protocol, runtime_checkable
from urllib.error import HTTPError

import pytest


@runtime_checkable
class PublicationVerifier(Protocol):
    def main(self, argv: list[str] | None = None) -> int: ...


class PackageIdentity(NamedTuple):
    name: str
    version: str


@pytest.fixture
def verifier(monkeypatch: pytest.MonkeyPatch) -> PublicationVerifier:
    path = Path(__file__).resolve().parents[4] / ".github/scripts/verify_registry_publication.py"
    spec = importlib.util.spec_from_file_location("registry_publication_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    def identity(_tarball: Path) -> PackageIdentity:
        return PackageIdentity("@example/plugin", "1.2.3")

    monkeypatch.setattr(module, "_npm_identity", identity)
    assert isinstance(module, PublicationVerifier)
    return module


@pytest.mark.parametrize(
    ("registry_status", "publish_flag", "expected_status", "expected_events"),
    [
        (200, True, 0, ["lookup", "verify"]),
        (404, True, 0, ["lookup", "publish", "verify"]),
        (401, True, 2, ["lookup"]),
        (403, True, 2, ["lookup"]),
        (429, True, 2, ["lookup"]),
        (500, True, 2, ["lookup"]),
        (404, False, 0, ["verify"]),
    ],
    ids=("existing", "missing", "unauthorized", "forbidden", "rate-limit", "server-error", "verify-only"),
)
def test_npm_publication_is_retry_safe(
    verifier: PublicationVerifier,
    monkeypatch: pytest.MonkeyPatch,
    registry_status: int,
    *,
    publish_flag: bool,
    expected_status: int,
    expected_events: list[str],
) -> None:
    events: list[str] = []

    def lookup(url: str) -> dict[str, object]:
        events.append("lookup")
        assert url == "https://registry.npmjs.org/%40example%2Fplugin/1.2.3"
        if registry_status != 200:
            raise HTTPError(url, registry_status, "registry response", Message(), None)
        return {}

    def publish(argv: tuple[str, ...], *, check: bool) -> None:
        events.append("publish")
        assert argv == ("npm", "publish", "package.tgz", "--access", "public", "--ignore-scripts")
        assert check

    def verify(tarball: Path, *, commit: str, environment: str) -> None:
        events.append("verify")
        assert (tarball, commit, environment) == (Path("package.tgz"), "commit", "publisher")

    monkeypatch.setattr(verifier, "_json", lookup)
    monkeypatch.setattr(subprocess, "run", publish)
    monkeypatch.setattr(verifier, "verify_npm", verify)
    argv = ["npm", "--tarball", "package.tgz", "--commit", "commit", "--environment", "publisher"]
    if publish_flag:
        argv.append("--publish")

    assert verifier.main(argv) == expected_status
    assert events == expected_events


@pytest.mark.parametrize("registry_status", [200, 404], ids=("existing", "newly-published"))
def test_npm_publication_never_accepts_failed_verification(
    verifier: PublicationVerifier, monkeypatch: pytest.MonkeyPatch, registry_status: int
) -> None:
    def lookup(url: str) -> dict[str, object]:
        if registry_status == 404:
            raise HTTPError(url, 404, "not found", Message(), None)
        return {}

    def reject(_tarball: Path, *, commit: str, environment: str) -> None:
        _ = commit, environment
        msg = "artifact or provenance mismatch"
        raise OSError(msg)

    def publish(_argv: tuple[str, ...], *, check: bool) -> None:
        assert check

    monkeypatch.setattr(verifier, "_json", lookup)
    monkeypatch.setattr(subprocess, "run", publish)
    monkeypatch.setattr(verifier, "verify_npm", reject)

    assert (
        verifier.main(
            ["npm", "--publish", "--tarball", "package.tgz", "--commit", "commit", "--environment", "publisher"]
        )
        == 2
    )


def test_retry_after_provenance_delay_does_not_republish(
    verifier: PublicationVerifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    def lookup(url: str) -> dict[str, object]:
        if "publish" not in events:
            raise HTTPError(url, 404, "not found", Message(), None)
        return {}

    def publish(_argv: tuple[str, ...], *, check: bool) -> None:
        assert check
        events.append("publish")

    def verify(_tarball: Path, *, commit: str, environment: str) -> None:
        _ = commit, environment
        events.append("verify")
        if events.count("verify") == 1:
            msg = "provenance is not visible yet"
            raise OSError(msg)

    monkeypatch.setattr(verifier, "_json", lookup)
    monkeypatch.setattr(subprocess, "run", publish)
    monkeypatch.setattr(verifier, "verify_npm", verify)
    argv = ["npm", "--publish", "--tarball", "package.tgz", "--commit", "commit", "--environment", "publisher"]

    assert verifier.main(argv) == 2
    assert verifier.main(argv) == 0
    assert events == ["publish", "verify", "verify"]
