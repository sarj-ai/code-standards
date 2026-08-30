from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tarfile
import tempfile
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal
from urllib.request import Request, urlopen
import zipfile


if TYPE_CHECKING:
    from collections.abc import Mapping


_MAX_ARTIFACT_BYTES: Final = 80 * 1024 * 1024
_MAX_MOBSF_RULE_BYTES: Final = 16 * 1024 * 1024
_READ_BYTES: Final = 1024 * 1024
_USER_AGENT: Final = "code-standards-mobile-tools/1"


@dataclass(frozen=True, slots=True)
class _Artifact:
    name: str
    version: str
    url: str
    sha256: str
    extracted_sha256: str | None = None
    archive_member: str | None = None


@dataclass(frozen=True, slots=True)
class _RulesArtifact:
    version: str
    url: str
    sha256: str
    rules_sha256: str
    rule_count: int


_ARTIFACTS: Final[Mapping[str, _Artifact]] = MappingProxyType(
    {
        "detekt": _Artifact(
            "detekt",
            "1.23.8",
            "https://github.com/detekt/detekt/releases/download/v1.23.8/detekt-cli-1.23.8-all.jar",
            "2ce2ff952e150baf28a29cda70a363b0340b3e81a55f43e51ec5edffc3d066c1",
        ),
        "ktlint": _Artifact(
            "ktlint",
            "1.8.0",
            "https://github.com/pinterest/ktlint/releases/download/1.8.0/ktlint",
            "a3fd620207d5c40da6ca789b95e7f823c54e854b7fade7f613e91096a3706d75",
        ),
        "mint": _Artifact(
            "mint",
            "0.18.0",
            "https://github.com/yonaskolb/Mint/releases/download/0.18.0/mint.zip",
            "ce44b0fc4ef3bc854ea43b2d2d3f96502d52231c0e0849ec212815121955f5ef",
            extracted_sha256="04e0553213da04cb0137b426d5607b95b8433ba61a3efb8b373541ab00515cc6",
            archive_member="mint",
        ),
    }
)

_MOBSF_RULES: Final = _RulesArtifact(
    "1.0.0",
    "https://files.pythonhosted.org/packages/67/81/3d484897ed52542b4dcb95a725e56e29dac34bbdc959383039020132729a/"
    "mobsfscan-1.0.0.tar.gz",
    "ab989a8defbc6f2d3b5633bbb5e1c3c5d90f3f45fd0de2cb60fa611f45101f27",
    "60347af6c5574310d8ceba400eddab5f61128d8325c8f55dfe5340093a56c615",
    51,
)


def command(name: Literal["detekt", "ktlint", "mint"]) -> tuple[str, ...]:
    artifact = _ARTIFACTS[name]
    if name == "mint" and sys.platform != "darwin":
        msg = "Swift mobile tools require macOS"
        raise OSError(msg)
    path = _provision(artifact)
    if name == "detekt":
        return ("java", "-jar", str(path))
    return (str(path),)


def mobsf_rules() -> Path:
    cache = _cache_root()
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"mobsfscan-rules-{_MOBSF_RULES.version}.tar.gz"
    destination = cache / f"mobsfscan-rules-{_MOBSF_RULES.version}"
    if _rules_match(destination):
        return destination
    download = _Artifact("mobsfscan", _MOBSF_RULES.version, _MOBSF_RULES.url, _MOBSF_RULES.sha256)
    if not _matches(archive, _MOBSF_RULES.sha256):
        _download(download, archive)
    _extract_mobsf_rules(archive, destination)
    if not _rules_match(destination):
        msg = "mobsfscan extracted rules checksum mismatch"
        raise OSError(msg)
    return destination


def _extract_mobsf_rules(archive: Path, destination: Path) -> None:
    prefix = PurePosixPath(f"mobsfscan-{_MOBSF_RULES.version}/mobsfscan/rules/semgrep")
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".mobsfscan-rules-") as temporary:
        extracted = Path(temporary) / "rules"
        extracted.mkdir()
        count = 0
        extracted_bytes = 0
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                relative = _mobsf_rule_relative(PurePosixPath(member.name), prefix=prefix)
                if relative is None:
                    continue
                if not member.isfile():
                    msg = f"mobsfscan rule is not a regular file: {relative}"
                    raise OSError(msg)
                if member.size < 0 or extracted_bytes + member.size > _MAX_MOBSF_RULE_BYTES:
                    msg = f"mobsfscan extracted rules exceed {_MAX_MOBSF_RULE_BYTES} bytes"
                    raise OSError(msg)
                stream = bundle.extractfile(member)
                if stream is None:
                    msg = f"mobsfscan rule cannot be read: {relative}"
                    raise OSError(msg)
                payload = stream.read(member.size + 1)
                if len(payload) != member.size:
                    msg = f"mobsfscan rule size mismatch: {relative}"
                    raise OSError(msg)
                extracted_bytes += len(payload)
                target = extracted.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write(target, payload)
                count += 1
        if count != _MOBSF_RULES.rule_count:
            msg = f"mobsfscan archive contained {count} actionable rules; expected {_MOBSF_RULES.rule_count}"
            raise OSError(msg)
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        elif destination.is_dir():
            shutil.rmtree(destination)
        extracted.replace(destination)


def _mobsf_rule_relative(path: PurePosixPath, *, prefix: PurePosixPath) -> PurePosixPath | None:
    try:
        relative = path.relative_to(prefix)
    except ValueError:
        return None
    if not relative.parts or "best_practices" in relative.parts:
        return None
    if relative.suffix not in {".yaml", ".yml"} or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    return relative


def _rules_match(path: Path) -> bool:
    if not path.is_dir() or path.is_symlink():
        return False
    files = sorted((*path.rglob("*.yaml"), *path.rglob("*.yml")), key=lambda item: item.relative_to(path).as_posix())
    if len(files) != _MOBSF_RULES.rule_count or any(file.is_symlink() or not file.is_file() for file in files):
        return False
    digest = hashlib.sha256()
    try:
        for file in files:
            relative = file.relative_to(path).as_posix()
            digest.update(relative.encode())
            digest.update(b"\0")
            digest.update(file.read_bytes())
            digest.update(b"\0")
    except OSError:
        return False
    return digest.hexdigest() == _MOBSF_RULES.rules_sha256


def _provision(artifact: _Artifact) -> Path:
    cache = _cache_root()
    cache.mkdir(parents=True, exist_ok=True)
    suffix = ".zip" if artifact.archive_member is not None else ".jar" if artifact.name == "detekt" else ""
    archive = cache / f"{artifact.name}-{artifact.version}{suffix}"
    destination = cache / f"{artifact.name}-{artifact.version}"
    if artifact.archive_member is None:
        destination = archive
        if _matches(destination, artifact.sha256):
            _make_executable(destination)
            return destination
        _download(artifact, destination)
        _make_executable(destination)
        return destination
    if artifact.extracted_sha256 is None:
        msg = f"{artifact.name} archive has no extracted checksum"
        raise ValueError(msg)
    if _matches(destination, artifact.extracted_sha256):
        _make_executable(destination)
        return destination
    if not _matches(archive, artifact.sha256):
        _download(artifact, archive)
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if names != [artifact.archive_member]:
            msg = f"{artifact.name} archive contains unexpected members"
            raise OSError(msg)
        payload = bundle.read(artifact.archive_member)
    if hashlib.sha256(payload).hexdigest() != artifact.extracted_sha256:
        msg = f"{artifact.name} extracted checksum mismatch"
        raise OSError(msg)
    _atomic_write(destination, payload)
    _make_executable(destination)
    return destination


def _cache_root() -> Path:
    configured = os.environ.get("XDG_CACHE_HOME", "").strip()  # ruff: ignore[banned-api] -- standard cache location.
    base = Path(configured).expanduser() if configured else Path.home() / ".cache"
    return base / "code-standards" / "mobile-tools"


def _download(artifact: _Artifact, destination: Path) -> None:
    request = Request(  # ruff: ignore[suspicious-url-open-usage] -- fixed HTTPS release origins.
        artifact.url,
        headers={"User-Agent": _USER_AGENT},
    )
    digest = hashlib.sha256()
    size = 0
    with (
        urlopen(request, timeout=120) as response,  # ruff: ignore[suspicious-url-open-usage]  # pyright: ignore[reportAny] -- fixed HTTPS release origins.
        tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{artifact.name}-", delete=False) as stream,
    ):
        temporary = Path(stream.name)
        try:  # ruff: ignore[too-many-statements-in-try-clause] -- atomic bounded stream copy.
            while True:
                chunk = response.read(_READ_BYTES)  # pyright: ignore[reportAny]
                if not isinstance(chunk, bytes):
                    msg = f"{artifact.name} returned a non-bytes response"
                    raise OSError(msg)  # ruff: ignore[raise-within-try] -- cleanup is required before propagation.
                if not chunk:
                    break
                size += len(chunk)
                if size > _MAX_ARTIFACT_BYTES:
                    msg = f"{artifact.name} artifact exceeds {_MAX_ARTIFACT_BYTES} bytes"
                    raise OSError(msg)  # ruff: ignore[raise-within-try] -- cleanup is required before propagation.
                digest.update(chunk)
                _ = stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    if digest.hexdigest() != artifact.sha256:
        temporary.unlink(missing_ok=True)
        msg = f"{artifact.name} download checksum mismatch"
        raise OSError(msg)
    temporary.replace(destination)


def _atomic_write(destination: Path, payload: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            _ = stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    temporary.replace(destination)


def _matches(path: Path, expected: str) -> bool:
    if not path.is_file():
        return False
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_READ_BYTES):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected


def _make_executable(path: Path) -> None:
    if path.name.startswith("detekt-"):
        return
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
