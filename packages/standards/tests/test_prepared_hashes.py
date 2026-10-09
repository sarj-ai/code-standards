from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import tracemalloc
from typing import TYPE_CHECKING

import pytest

from sarj_standards.libs.adoption.manifest import PreparedTarget
from sarj_standards.libs.diagnostics import Completion
from sarj_standards.libs.linting.prepared_devops import analyze_prepared


if TYPE_CHECKING:
    from sarj_standards.libs.diagnostics import ToolReport


@dataclass(frozen=True, slots=True)
class _HashFixture:
    root: Path
    payload: Path
    target: dict[str, object]
    hashes: dict[str, str]


def _fixture(root: Path, content: bytes = b"artifact content") -> _HashFixture:
    source = root / "deploy.yaml"
    source.write_text("authored source\n", encoding="utf-8")
    manifest = root / "resource.yaml"
    manifest.write_text(
        "apiVersion: serving.knative.dev/v1\nkind: Service\nmetadata:\n  name: example\n", encoding="utf-8"
    )
    schema = root / "schema.json"
    schema.write_text('{"type":"object","required":["metadata"]}', encoding="utf-8")
    payload = root / "payload.bin"
    payload.write_bytes(content)
    hashes = {path.name: sha256(path.read_bytes()).hexdigest() for path in (manifest, schema, payload)}
    target: dict[str, object] = {
        "id": "example",
        "source": "deploy.yaml",
        "source_sha256": sha256(source.read_bytes()).hexdigest(),
        "kind": "cloud-run",
        "manifests": ["resource.yaml"],
        "schema_bindings": {"serving.knative.dev/v1/Service": "schema.json"},
        "artifacts": hashes,
    }
    return _HashFixture(root, payload, target, hashes)


def _report(fixture: _HashFixture, *, receipt_size: int = 0) -> ToolReport:
    body = json.dumps({"version": 1, "targets": [fixture.target]})
    receipt = fixture.root / "receipt.json"
    receipt.write_text(body.ljust(receipt_size), encoding="utf-8")
    [report] = analyze_prepared((receipt,), root=fixture.root, declared=(PreparedTarget("example", "deploy.yaml"),))
    return report


@pytest.mark.parametrize("size", [0, 262145, 2 * 1024 * 1024], ids=("empty", "multi-chunk", "two-mib"))
def test_prepared_hash_accepts_complete_content_and_repeated_calls(tmp_path: Path, size: int) -> None:
    fixture = _fixture(tmp_path, bytes(range(256)) * (size // 256) + b"x" * (size % 256))
    first = _report(fixture)
    assert first.completion is Completion.COMPLETE
    assert _report(fixture) == first


def test_prepared_hash_accepts_receipt_at_size_limit(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    assert _report(fixture, receipt_size=2 * 1024 * 1024).completion is Completion.COMPLETE
    report = _report(fixture, receipt_size=2 * 1024 * 1024 + 1)
    assert report.completion is Completion.FAILED
    assert report.issues[0].message == "prepared receipt must be a bounded regular file"


def test_prepared_hash_does_not_retain_large_artifact(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, b"x" * (8 * 1024 * 1024))
    tracemalloc.start()
    try:
        report = _report(fixture)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert report.completion is Completion.COMPLETE
    assert peak < 2 * 1024 * 1024


def test_prepared_hash_checks_authored_inputs_and_changed_final_chunk(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, b"x" * (2 * 1024 * 1024))
    fixture.target["source_inputs"] = {
        "deploy.yaml": fixture.target["source_sha256"],
        "payload.bin": fixture.hashes["payload.bin"],
    }
    assert _report(fixture).completion is Completion.COMPLETE
    with fixture.payload.open("r+b") as stream:
        stream.seek(-1, 2)
        stream.write(b"y")
    report = _report(fixture)
    assert report.completion is Completion.FAILED
    assert report.issues[0].message == "prepared artifact hash does not match: payload.bin"


@pytest.mark.parametrize("boundary", ["source", "source-input", "artifact"])
@pytest.mark.parametrize(
    "mutation", ["wrong", "uppercase", "short", "long", "nonhex"], ids=("wrong", "uppercase", "short", "long", "nonhex")
)
def test_prepared_hash_preserves_exact_digest_admission(tmp_path: Path, boundary: str, mutation: str) -> None:
    fixture = _fixture(tmp_path)
    name = "deploy.yaml" if boundary == "source" else "payload.bin"
    digest = sha256((tmp_path / name).read_bytes()).hexdigest()
    match mutation:
        case "wrong":
            digest = "0" * 64
        case "uppercase":
            digest = digest.upper()
        case "short":
            digest = digest[:-1]
        case "long":
            digest += "0"
        case _:
            digest = "g" * 64
    match boundary:
        case "source":
            fixture.target["source_sha256"] = digest
        case "source-input":
            fixture.target["source_inputs"] = {"deploy.yaml": fixture.target["source_sha256"], name: digest}
        case _:
            fixture.hashes[name] = digest
    report = _report(fixture)
    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "invalid-input"
    assert report.issues[0].message == f"prepared artifact hash does not match: {name}"


@pytest.mark.parametrize("mutation", ["missing", "symlink", "symlink-directory", "escape", "absolute", "backslash"])
def test_prepared_hash_preserves_path_admission(tmp_path: Path, mutation: str) -> None:
    fixture = _fixture(tmp_path)
    name = "payload.bin"
    match mutation:
        case "missing":
            fixture.payload.unlink()
            message = "prepared artifact is missing or outside its directory: payload.bin"
        case "symlink":
            destination = tmp_path / "original.bin"
            fixture.payload.rename(destination)
            fixture.payload.symlink_to(destination)
            message = "prepared path cannot contain a symlink: payload.bin"
        case "symlink-directory":
            (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
            name = "alias/payload.bin"
            message = f"prepared path cannot contain a symlink: {name}"
        case "escape":
            name = "../payload.bin"
            message = f"prepared path must stay beneath its directory: {name}"
        case "absolute":
            name = str(fixture.payload)
            message = f"prepared path must stay beneath its directory: {name}"
        case _:
            name = "alias\\payload.bin"
            message = f"prepared path must stay beneath its directory: {name}"
    fixture.hashes[name] = fixture.hashes.pop("payload.bin")
    report = _report(fixture)
    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "invalid-input"
    assert report.issues[0].message == message


@pytest.mark.parametrize("digest", ["0" * 64, "short"], ids=("read-error", "length-short-circuit"))
def test_prepared_hash_preserves_unreadable_file_failure(tmp_path: Path, digest: str) -> None:
    fixture = _fixture(tmp_path)
    fixture.hashes["payload.bin"] = digest
    fixture.payload.chmod(0)
    try:
        report = _report(fixture)
    finally:
        fixture.payload.chmod(0o600)
    assert report.completion is Completion.FAILED
    assert report.issues[0].kind == "invalid-input"
    if len(digest) == 64:
        assert "Permission denied" in report.issues[0].message
        assert "payload.bin" in report.issues[0].message
    else:
        assert report.issues[0].message == "prepared artifact hash does not match: payload.bin"
