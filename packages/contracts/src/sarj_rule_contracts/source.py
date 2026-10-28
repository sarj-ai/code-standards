from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NewType


if TYPE_CHECKING:
    from typing import Self


ByteDigest = NewType("ByteDigest", str)
TextDigest = NewType("TextDigest", str)
type DecodeErrors = Literal["strict", "surrogateescape", "replace"]


class NewlinePolicy(StrEnum):
    PRESERVE = "preserve"
    UNIVERSAL = "universal"


@dataclass(frozen=True, slots=True)
class DocumentIdentity:
    path: Path
    raw_sha256: ByteDigest


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    path: Path
    raw: bytes = field(repr=False)
    _identity: DocumentIdentity | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.raw) is not bytes:
            msg = "captured source requires immutable bytes"
            raise TypeError(msg)

    @property
    def identity(self) -> DocumentIdentity:
        identity = self._identity
        if identity is None:
            identity = DocumentIdentity(self.path, ByteDigest(sha256(self.raw).hexdigest()))
            object.__setattr__(self, "_identity", identity)  # ruff: ignore[unnecessary-dunder-call] -- frozen snapshots permit only their private lazy cache to change.
        return identity

    @classmethod
    def read(cls, path: Path) -> Self:
        return cls(path, path.read_bytes())

    def decode(
        self,
        encoding: str,
        *,
        errors: DecodeErrors = "strict",
        newlines: NewlinePolicy = NewlinePolicy.PRESERVE,
    ) -> DecodedSource:
        return DecodedSource(self, encoding, errors, newlines)


class SourceCatalog:
    def __init__(self) -> None:
        self._snapshots: dict[Path, SourceSnapshot] = {}

    def capture(self, path: Path) -> SourceSnapshot:
        snapshot = self._snapshots.get(path)
        if snapshot is None:
            snapshot = SourceSnapshot.read(path)
            self._snapshots[path] = snapshot
        return snapshot

    def get(self, path: Path) -> SourceSnapshot | None:
        return self._snapshots.get(path)


@dataclass(frozen=True, slots=True)
class DecodedSource:
    snapshot: SourceSnapshot
    encoding: str
    errors: DecodeErrors = "strict"
    newlines: NewlinePolicy = NewlinePolicy.PRESERVE
    text: str = field(init=False, repr=False)
    _text_sha256: TextDigest | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.errors not in ("strict", "surrogateescape", "replace"):  # ruff: ignore[literal-membership] -- invalid runtime values may be unhashable and must receive the same validation error.
            msg = "source decoding errors must be strict, surrogateescape or replace"
            raise ValueError(msg)
        newlines = NewlinePolicy(self.newlines)
        object.__setattr__(self, "newlines", newlines)
        text = self.snapshot.raw.decode(self.encoding, errors=self.errors)
        if newlines is NewlinePolicy.UNIVERSAL:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        object.__setattr__(self, "text", text)

    @property
    def text_sha256(self) -> TextDigest:
        digest = self._text_sha256
        if digest is not None:
            return digest
        # This identifies decoded characters, including lossless surrogateescape views.
        digest = TextDigest(sha256(self.text.encode("utf-8", "surrogatepass")).hexdigest())
        object.__setattr__(self, "_text_sha256", digest)  # ruff: ignore[unnecessary-dunder-call] -- memoize a digest without making the decoded source mutable.
        return digest
