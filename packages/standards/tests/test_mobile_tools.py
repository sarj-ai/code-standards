from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tarfile

from pydantic import TypeAdapter
import pytest

from sarj_standards.libs.linting import mobile_tools


def test_managed_mobile_tool_pins_match_the_shipped_version_manifest() -> None:
    versions_path = Path(mobile_tools.__file__).parents[2] / "configs" / "mobile-tools.versions.json"
    versions = TypeAdapter(dict[str, str]).validate_json(versions_path.read_text(encoding="utf-8"))

    assert {
        name: artifact.version
        for name, artifact in mobile_tools._ARTIFACTS.items()  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
    } == {
        "detekt": versions["detekt"],
        "ktlint": versions["ktlint"],
        "mint": versions["mint"],
    }
    assert mobile_tools._MOBSF_RULES.version == versions["mobsfscan"]  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
    assert mobile_tools._MOBSF_RULES.url.startswith("https://files.pythonhosted.org/")  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
    artifacts = mobile_tools._ARTIFACTS  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- verifies fixed origins and digests.
    assert all(artifact.url.startswith("https://github.com/") for artifact in artifacts.values())
    assert all(len(artifact.sha256) == 64 for artifact in artifacts.values())


def test_cached_tool_is_checksum_verified_without_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"fixture executable"
    artifact = mobile_tools._Artifact(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage] -- focused cache-boundary fixture.
        "ktlint",
        "test",
        "https://github.com/example/example/releases/download/test/ktlint",
        hashlib.sha256(payload).hexdigest(),
    )
    monkeypatch.setattr(mobile_tools, "_cache_root", lambda: tmp_path)
    cached = tmp_path / "ktlint-test"
    cached.write_bytes(payload)

    assert mobile_tools._provision(artifact) == cached  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
    assert cached.stat().st_mode & 0o100


def test_detekt_uses_the_pinned_jar_through_java(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jar = tmp_path / "detekt.jar"

    def provision(_artifact: object) -> Path:
        return jar

    monkeypatch.setattr(mobile_tools, "_provision", provision)

    assert mobile_tools.command("detekt") == ("java", "-jar", str(jar))


def test_mobsf_rules_are_checksum_verified_and_exclude_presence_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    actionable_name = "mobsfscan-test/mobsfscan/rules/semgrep/swift/crypto.yaml"
    best_practice_name = "mobsfscan-test/mobsfscan/rules/semgrep/best_practices/swift/jailbreak.yaml"
    actionable = b"rules:\n  - id: actionable\n    message: actionable\n    severity: ERROR\n"
    archive = tmp_path / "fixture.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name, payload in ((actionable_name, actionable), (best_practice_name, b"rules: []\n")):
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            bundle.addfile(member, io.BytesIO(payload))
    digest = hashlib.sha256()
    digest.update(b"swift/crypto.yaml\0")
    digest.update(actionable)
    digest.update(b"\0")
    fixture = mobile_tools._RulesArtifact(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        "test",
        "https://files.pythonhosted.org/fixture.tar.gz",
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        digest.hexdigest(),
        1,
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    cached_archive = cache / "mobsfscan-rules-test.tar.gz"
    cached_archive.write_bytes(archive.read_bytes())
    monkeypatch.setattr(mobile_tools, "_cache_root", lambda: cache)
    monkeypatch.setattr(mobile_tools, "_MOBSF_RULES", fixture)

    rules = mobile_tools.mobsf_rules()

    assert (
        rules / "swift" / "crypto.yaml"
    ).read_bytes() == actionable  # sarj-noqa: SARJ402 -- extracted rule bytes are the archive-integrity contract
    assert not (rules / "best_practices").exists()
    assert mobile_tools.mobsf_rules() == rules


def test_mobsf_rule_extraction_rejects_symlink_members(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "fixture.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("mobsfscan-symlink/mobsfscan/rules/semgrep/swift/crypto.yaml")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../outside.yaml"
        bundle.addfile(member)
    _configure_mobsf_archive(tmp_path, monkeypatch, archive, version="symlink")

    with pytest.raises(OSError, match="not a regular file"):
        mobile_tools.mobsf_rules()


def test_mobsf_rule_extraction_enforces_an_aggregate_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "fixture.tar.gz"
    payload = b"rules: []\n"
    with tarfile.open(archive, "w:gz") as bundle:
        member = tarfile.TarInfo("mobsfscan-oversized/mobsfscan/rules/semgrep/swift/crypto.yaml")
        member.size = len(payload)
        bundle.addfile(member, io.BytesIO(payload))
    _configure_mobsf_archive(tmp_path, monkeypatch, archive, version="oversized")
    monkeypatch.setattr(mobile_tools, "_MAX_MOBSF_RULE_BYTES", len(payload) - 1)

    with pytest.raises(OSError, match="extracted rules exceed"):
        mobile_tools.mobsf_rules()


def _configure_mobsf_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    archive: Path,
    *,
    version: str,
) -> None:
    fixture = mobile_tools._RulesArtifact(  # ruff: ignore[private-member-access]  # pyright: ignore[reportPrivateUsage]
        version,
        "https://files.pythonhosted.org/fixture.tar.gz",
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        "0" * 64,
        1,
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"mobsfscan-rules-{version}.tar.gz").write_bytes(archive.read_bytes())
    monkeypatch.setattr(mobile_tools, "_cache_root", lambda: cache)
    monkeypatch.setattr(mobile_tools, "_MOBSF_RULES", fixture)
