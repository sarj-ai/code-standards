from __future__ import annotations

import base64
from datetime import timedelta
from email.message import Message
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
from typing import TYPE_CHECKING, NamedTuple, Protocol, runtime_checkable
from urllib.error import HTTPError

import pytest


if TYPE_CHECKING:
    from collections.abc import Callable


@runtime_checkable
class PublicationVerifier(Protocol):
    def main(self, argv: list[str] | None = None) -> int: ...

    def verify_npm(
        self,
        tarball: Path,
        *,
        commit: str,
        environment: str,
        clock: Callable[[], float] = ...,
        sleeper: Callable[[float], None] = ...,
    ) -> None: ...

    def retry_npm_stage[T](
        self,
        stage: str,
        operation: Callable[[], T],
        *,
        timeout: timedelta,
        clock: Callable[[], float],
        sleeper: Callable[[float], None],
    ) -> T: ...

    def _npm_artifact(self, tarball: Path, identity: PackageIdentity) -> object: ...

    def attested_commit_matches_current_tree(self, package: str, attested: str, current: str) -> bool: ...


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


def _argv() -> list[str]:
    return ["npm", "--publish", "--tarball", "package.tgz", "--commit", "commit", "--environment", "publisher"]


def _missing(_identity: PackageIdentity) -> bool:
    return False


@pytest.mark.parametrize(
    ("exists", "expected_events"),
    [(True, ["lookup", "verify"]), (False, ["lookup", "publish", "verify"])],
    ids=("already-published", "new-publication"),
)
def test_publish_command_is_idempotent(
    verifier: PublicationVerifier,
    monkeypatch: pytest.MonkeyPatch,
    *,
    exists: bool,
    expected_events: list[str],
) -> None:
    events: list[str] = []

    def lookup(_identity: PackageIdentity) -> bool:
        events.append("lookup")
        return exists

    def run(argv: tuple[str, ...], *, check: bool, timeout: int) -> None:
        events.append("publish")
        assert argv == ("npm", "publish", "package.tgz", "--access", "public", "--ignore-scripts")
        assert check
        assert timeout == 120

    def verify(tarball: Path, *, commit: str, environment: str) -> None:
        events.append("verify")
        assert (tarball, commit, environment) == (Path("package.tgz"), "commit", "publisher")

    monkeypatch.setattr(verifier, "_npm_version_exists", lookup)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(verifier, "verify_npm", verify)

    assert verifier.main(_argv()) == 0
    assert events == expected_events


def test_ambiguous_publish_failure_is_accepted_only_after_exact_verification(
    verifier: PublicationVerifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    monkeypatch.setattr(verifier, "_npm_version_exists", _missing)

    def publish(_argv: tuple[str, ...], *, check: bool, timeout: int) -> None:
        _ = check, timeout
        raise subprocess.CalledProcessError(1, "npm publish")

    def verify(_tarball: Path, *, commit: str, environment: str) -> None:
        nonlocal calls
        _ = commit, environment
        calls += 1

    monkeypatch.setattr(subprocess, "run", publish)
    monkeypatch.setattr(verifier, "verify_npm", verify)

    assert verifier.main(_argv()) == 0
    assert calls == 1


def test_ambiguous_publish_and_verification_failure_reports_failure(
    verifier: PublicationVerifier, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(verifier, "_npm_version_exists", _missing)

    def publish(_argv: tuple[str, ...], *, check: bool, timeout: int) -> None:
        _ = check, timeout
        raise subprocess.CalledProcessError(1, "npm publish")

    def reject(_tarball: Path, *, commit: str, environment: str) -> None:
        _ = commit, environment
        msg = "registry never converged"
        raise OSError(msg)

    monkeypatch.setattr(subprocess, "run", publish)
    monkeypatch.setattr(verifier, "verify_npm", reject)

    assert verifier.main(_argv()) == 2
    error = capsys.readouterr().err
    assert "ambiguous failure" in error
    assert "registry never converged" in error


def test_retry_stage_respects_retry_after_then_uses_backoff(verifier: PublicationVerifier) -> None:
    now = 0.0
    waits: list[float] = []
    attempts = 0

    def clock() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        waits.append(seconds)
        now += seconds

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            headers = Message()
            headers["Retry-After"] = "7"
            url = "https://registry.example"
            raise HTTPError(url, 429, "busy", headers, None)
        if attempts == 2:
            msg = "temporary resolver failure"
            raise OSError(msg)
        return "ready"

    assert (
        verifier.retry_npm_stage("test", operation, timeout=timedelta(minutes=1), clock=clock, sleeper=sleep) == "ready"
    )
    assert waits == [7.0, 10.0]


@pytest.mark.parametrize("status", [401, 403], ids=("unauthorized", "forbidden"))
def test_retry_stage_fails_fast_on_nonretryable_http_status(verifier: PublicationVerifier, status: int) -> None:
    sleeps: list[float] = []

    def operation() -> None:
        url = "https://registry.example"
        raise HTTPError(url, status, "denied", Message(), None)

    with pytest.raises(HTTPError):
        verifier.retry_npm_stage(
            "test",
            operation,
            timeout=timedelta(minutes=1),
            clock=lambda: 0,
            sleeper=sleeps.append,
        )
    assert sleeps == []


def test_retry_stage_has_a_bounded_monotonic_deadline(verifier: PublicationVerifier) -> None:
    now = 0.0
    waits: list[float] = []

    def clock() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        waits.append(seconds)
        now += seconds

    def fail() -> None:
        msg = "offline"
        raise OSError(msg)

    with pytest.raises(Exception, match="did not converge within"):
        verifier.retry_npm_stage("test", fail, timeout=timedelta(seconds=12), clock=clock, sleeper=sleep)
    assert waits == [5.0, 7.0]


def test_npm_verification_has_independent_stage_budgets(
    verifier: PublicationVerifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    stages: list[tuple[str, timedelta]] = []
    identity = PackageIdentity("@example/plugin", "1.2.3")
    artifact = object()

    def retry(
        stage: str,
        operation: Callable[[], object],
        *,
        timeout: timedelta,
        clock: Callable[[], float],
        sleeper: Callable[[float], None],
    ) -> object:
        _ = clock, sleeper
        stages.append((stage, timeout))
        return operation()

    def read_identity(_tarball: Path) -> PackageIdentity:
        return identity

    def read_artifact(_tarball: Path, _identity: PackageIdentity) -> object:
        return artifact

    def verify_provenance(_artifact: object, *, commit: str, environment: str) -> None:
        _ = commit, environment

    def verify_installability(_identity: PackageIdentity) -> None:
        return None

    monkeypatch.setattr(verifier, "retry_npm_stage", retry)
    monkeypatch.setattr(verifier, "_npm_identity", read_identity)
    monkeypatch.setattr(verifier, "_npm_artifact", read_artifact)
    monkeypatch.setattr(verifier, "_verify_npm_provenance", verify_provenance)
    monkeypatch.setattr(verifier, "_verify_npm_installability", verify_installability)

    verifier.verify_npm(Path("package.tgz"), commit="commit", environment="publisher")

    assert stages == [
        ("metadata and exact bytes", timedelta(minutes=5)),
        ("provenance", timedelta(minutes=10)),
        ("package-spec installability and signature audit", timedelta(minutes=10)),
    ]


def test_npm_verification_converges_independently_after_each_stage_is_delayed(
    verifier: PublicationVerifier, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = 0.0
    waits: list[float] = []
    attempts = {"metadata": 0, "provenance": 0, "install": 0}
    artifact = object()

    def clock() -> float:
        return now

    def sleep(seconds: float) -> None:
        nonlocal now
        waits.append(seconds)
        now += seconds

    def delayed(name: str, result: object = None) -> object:
        attempts[name] += 1
        if attempts[name] == 1:
            message = f"{name} has not propagated"
            raise OSError(message)
        return result

    def delayed_metadata(_tarball: Path, _identity: PackageIdentity) -> object:
        return delayed("metadata", artifact)

    def delayed_provenance(_artifact: object, *, commit: str, environment: str) -> object:
        _ = commit, environment
        return delayed("provenance")

    def delayed_install(_identity: PackageIdentity) -> object:
        return delayed("install")

    monkeypatch.setattr(verifier, "_npm_artifact", delayed_metadata)
    monkeypatch.setattr(verifier, "_verify_npm_provenance", delayed_provenance)
    monkeypatch.setattr(verifier, "_verify_npm_installability", delayed_install)

    verifier.verify_npm(
        Path("package.tgz"),
        commit="commit",
        environment="publisher",
        clock=clock,
        sleeper=sleep,
    )

    assert attempts == {"metadata": 2, "provenance": 2, "install": 2}
    assert waits == [5.0, 5.0, 5.0]


def test_wrong_registry_bytes_are_permanent_and_never_retried(
    verifier: PublicationVerifier, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tarball = tmp_path / "package.tgz"
    expected = b"expected artifact"
    tarball.write_bytes(expected)
    integrity = base64.b64encode(hashlib.sha512(expected).digest()).decode()
    metadata = {
        "dist": {
            "tarball": "https://registry.example/package.tgz",
            "shasum": hashlib.sha1(expected).hexdigest(),  # ruff: ignore[hashlib-insecure-hash-function] -- npm publishes SHA-1 metadata.
            "integrity": f"sha512-{integrity}",
        }
    }

    def registry_metadata(_url: str) -> dict[str, dict[str, str]]:
        return metadata

    def registry_bytes(_url: str) -> bytes:
        return b"different artifact"

    monkeypatch.setattr(verifier, "_json", registry_metadata)
    monkeypatch.setattr(verifier, "_bytes", registry_bytes)
    sleeps: list[float] = []

    with pytest.raises(Exception, match="bytes differ"):
        verifier.verify_npm(
            tarball,
            commit="commit",
            environment="publisher",
            clock=lambda: 0,
            sleeper=sleeps.append,
        )

    assert sleeps == []


@pytest.mark.parametrize(
    ("returncodes", "expected"),
    [([0, 0], True), ([1], False), ([0, 1], False)],
    ids=("unchanged-ancestor", "non-ancestor", "artifact-changed"),
)
def test_attested_commit_must_be_an_unchanged_ancestor(
    verifier: PublicationVerifier,
    monkeypatch: pytest.MonkeyPatch,
    returncodes: list[int],
    *,
    expected: bool,
) -> None:
    calls: list[tuple[str, ...]] = []
    codes = iter(returncodes)

    def run(argv: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, next(codes))

    monkeypatch.setattr(subprocess, "run", run)
    attested = "a" * 40
    current = "b" * 40

    assert verifier.attested_commit_matches_current_tree("@sarj/eslint-plugin", attested, current) is expected
    assert calls[0] == ("git", "merge-base", "--is-ancestor", attested, current)
    if len(returncodes) == 2:
        assert calls[1] == (
            "git",
            "diff",
            "--quiet",
            attested,
            current,
            "--",
            "packages/typescript/LICENSE",
            "packages/typescript/package.json",
            "packages/typescript/src",
        )
