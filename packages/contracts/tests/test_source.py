from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from pathlib import Path
from typing import Protocol

import pytest

from sarj_rule_contracts import ByteDigest, NewlinePolicy, SourceCatalog, SourceSnapshot, TextDigest
import sarj_rule_contracts.source as source_contracts


class _HexDigest(Protocol):
    def hexdigest(self) -> str: ...


def test_snapshot_identity_distinguishes_raw_bytes_from_decoded_characters() -> None:
    raw = b"\xef\xbb\xbf" + "name = '😀'\r\n".encode()
    snapshot = SourceSnapshot(Path("nested/../source.py"), raw)
    physical = snapshot.decode("utf-8-sig")
    parser = snapshot.decode("utf-8-sig", newlines=NewlinePolicy.UNIVERSAL)

    assert snapshot.path.parts == ("nested", "..", "source.py")
    assert not snapshot.path.is_absolute()
    assert snapshot.identity.path == snapshot.path
    assert snapshot.identity.raw_sha256 == ByteDigest(sha256(raw).hexdigest())
    assert physical.text == "name = '😀'\r\n"
    assert parser.text == "name = '😀'\n"
    assert physical.text_sha256 == TextDigest(sha256(physical.text.encode()).hexdigest())
    assert parser.text_sha256 == TextDigest(sha256(parser.text.encode()).hexdigest())
    assert str(snapshot.identity.raw_sha256) != str(physical.text_sha256)
    assert physical.text_sha256 != parser.text_sha256
    assert physical.snapshot is parser.snapshot is snapshot


def test_decoded_digest_has_an_explicit_lossless_surrogate_policy() -> None:
    snapshot = SourceSnapshot(Path("legacy.txt"), b"value = '\xff'\r\n")
    with pytest.raises(UnicodeDecodeError):
        snapshot.decode("utf-8")

    decoded = snapshot.decode("utf-8", errors="surrogateescape")

    assert decoded.text.encode("utf-8", "surrogateescape") == snapshot.raw
    assert decoded.text_sha256 == TextDigest(sha256(decoded.text.encode("utf-8", "surrogatepass")).hexdigest())
    assert str(decoded.text_sha256) != str(snapshot.identity.raw_sha256)


def test_digests_are_lazy_and_memoized_without_changing_snapshot_equality(monkeypatch: pytest.MonkeyPatch) -> None:
    hashed: list[bytes] = []

    def count_hash(data: bytes) -> _HexDigest:
        hashed.append(data)
        return sha256(data)

    monkeypatch.setattr(  # sarj-noqa: SARJ445 -- retain real hashing and count the digest boundary to rule out hot-path hashing.
        source_contracts, "sha256", count_hash
    )
    raw = b"value = 1\r\n"
    snapshot = SourceSnapshot(Path("app.py"), raw)
    same = SourceSnapshot(snapshot.path, raw)
    decoded = snapshot.decode("utf-8", newlines=NewlinePolicy.UNIVERSAL)
    assert decoded.text == "value = 1\n"
    assert hashed == []

    identity = snapshot.identity
    assert snapshot.identity is identity
    assert hashed == [raw]
    digest = decoded.text_sha256
    assert decoded.text_sha256 is digest
    assert hashed == [raw, b"value = 1\n"]
    assert snapshot == same


def test_capture_does_not_read_again_and_a_later_capture_observes_changes(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_bytes(b"before\r\n")
    original = SourceSnapshot.read(path)
    path.write_bytes(b"after\n")

    assert original.raw == b"before\r\n"
    assert original.decode("utf-8").text == "before\r\n"
    replacement = SourceSnapshot.read(path)
    assert replacement.raw == b"after\n"
    assert replacement.identity.path == original.identity.path
    assert replacement.identity.raw_sha256 != original.identity.raw_sha256
    path.unlink()
    assert original.decode("utf-8").text == "before\r\n"


def test_captured_sources_and_decoded_views_are_immutable() -> None:
    snapshot = SourceSnapshot(Path("source.py"), b"value = 1\n")
    decoded = snapshot.decode("utf-8")

    with pytest.raises(FrozenInstanceError):
        snapshot.raw = b"changed\n"  # pyright: ignore[reportAttributeAccessIssue] -- exercise the runtime immutability contract with an invalid assignment.
    with pytest.raises(FrozenInstanceError):
        decoded.text = "changed\n"  # pyright: ignore[reportAttributeAccessIssue] -- a decoded view cannot drift from its captured bytes.


def test_source_representations_exclude_captured_file_contents() -> None:
    snapshot = SourceSnapshot(Path("source.txt"), b"private-source-content\r\n")
    decoded = snapshot.decode("utf-8", newlines=NewlinePolicy.UNIVERSAL)

    assert "private-source-content" not in repr(snapshot)
    assert "private-source-content" not in repr(decoded)
    assert "source.txt" in repr(snapshot)
    assert decoded.text == "private-source-content\n"


def test_catalog_keeps_exact_path_keys_and_first_capture_within_one_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    relative = Path("source.txt")
    absolute = tmp_path / relative
    absolute.write_bytes(b"before\r\n")
    catalog = SourceCatalog()
    assert catalog.get(relative) is None
    original = catalog.capture(relative)
    absolute.write_bytes(b"after\n")

    assert catalog.capture(relative) is original
    assert original.raw == b"before\r\n"
    assert original.path == relative
    assert catalog.get(absolute) is None
    assert catalog.capture(absolute).raw == b"after\n"
    assert SourceCatalog().capture(relative).raw == b"after\n"
    absolute.unlink()
    assert catalog.capture(relative) is original
    assert catalog.get(Path("never-captured.txt")) is None


def test_snapshot_replacement_rejects_mutable_borrowing_after_identity_is_cached() -> None:
    snapshot = SourceSnapshot(Path("source.txt"), b"before\n")
    identity = snapshot.identity
    mutable = bytearray(snapshot.raw)

    with pytest.raises(TypeError, match="immutable bytes"):
        replace(snapshot, raw=mutable)
    mutable[:] = b"after\n"

    assert snapshot.raw == b"before\n"
    assert snapshot.identity is identity
    assert snapshot.identity.raw_sha256 == ByteDigest(sha256(b"before\n").hexdigest())


def test_untyped_valid_newline_policy_is_normalized_instead_of_silently_ignored() -> None:
    snapshot = SourceSnapshot(Path("source.txt"), b"first\r\nsecond\r")
    decoded = replace(snapshot.decode("utf-8"), newlines="universal")

    assert decoded.newlines is NewlinePolicy.UNIVERSAL
    assert decoded.text == "first\nsecond\n"


@pytest.mark.parametrize("policy", ["ignore", "backslashreplace", "surrogatepass"])
def test_untyped_error_policies_cannot_discard_or_reinterpret_captured_bytes(policy: str) -> None:
    decoded = SourceSnapshot(Path("source.txt"), b"valid\n").decode("utf-8")

    with pytest.raises(ValueError, match="source decoding errors"):
        replace(decoded, errors=policy)


def test_unknown_untyped_newline_policy_is_rejected() -> None:
    decoded = SourceSnapshot(Path("source.txt"), b"value\r\n").decode("utf-8")

    with pytest.raises(ValueError, match="not a valid NewlinePolicy"):
        replace(decoded, newlines="platform")


def test_unhashable_untyped_error_policy_receives_a_validation_error() -> None:
    decoded = SourceSnapshot(Path("source.txt"), b"value\n").decode("utf-8")

    with pytest.raises(ValueError, match="source decoding errors"):
        replace(decoded, errors=[])
