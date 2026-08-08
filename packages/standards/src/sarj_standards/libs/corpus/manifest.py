"""Parse public corpus manifests and guarded private overlays."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import os
from pathlib import Path
import re
import stat
import tomllib
from typing import TypeIs

from sarj_standards.libs.filesystem import is_link_like


_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")


class CorpusKind(StrEnum):
    """How a local corpus checkout is pinned."""

    LOCAL = "local"
    GIT = "git"


class CorpusVisibility(StrEnum):
    """Whether corpus identities may appear in public reports."""

    PUBLIC = "public"
    PRIVATE = "private"


@dataclass(frozen=True, slots=True, repr=False)
class CorpusSource:
    """One locally available corpus with content and optional Git pins."""

    name: str = field(repr=False)
    root: Path = field(repr=False)
    kind: CorpusKind
    digest: str
    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    revision: str | None = None
    visibility: CorpusVisibility = CorpusVisibility.PUBLIC

    def __repr__(self) -> str:
        if self.visibility is CorpusVisibility.PRIVATE:
            return f"CorpusSource(name='<private-corpus>', kind={self.kind!r}, visibility={self.visibility!r})"
        return (
            f"CorpusSource(name={self.name!r}, root={self.root!r}, kind={self.kind!r}, "
            f"digest={self.digest!r}, include={self.include!r}, exclude={self.exclude!r}, "
            f"revision={self.revision!r}, visibility={self.visibility!r})"
        )

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("-", "").isalnum() or self.name != self.name.lower():
            msg = "corpus name must be non-empty lowercase kebab-case"
            raise ValueError(msg)
        if not _DIGEST.fullmatch(self.digest):
            msg = f"corpus {self.report_name} requires a sha256 content digest"
            raise ValueError(msg)
        if not self.include or any(not pattern.strip() for pattern in (*self.include, *self.exclude)):
            msg = f"corpus {self.report_name} requires non-empty include patterns"
            raise ValueError(msg)
        if self.kind is CorpusKind.GIT and (self.revision is None or not _REVISION.fullmatch(self.revision)):
            msg = f"git corpus {self.report_name} requires a full lowercase 40-character revision"
            raise ValueError(msg)
        if self.kind is CorpusKind.LOCAL and self.revision is not None:
            msg = f"local corpus {self.report_name} cannot declare a Git revision"
            raise ValueError(msg)

    @property
    def report_name(self) -> str:
        return self.name if self.visibility is CorpusVisibility.PUBLIC else "<private-corpus>"


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    """A versioned collection of reproducible local corpus sources."""

    origin: Path = field(repr=False)
    sources: tuple[CorpusSource, ...]
    private: bool = False
    schema: int = 1

    def __post_init__(self) -> None:
        if self.schema != 1:
            msg = f"unsupported corpus manifest schema: {self.schema}"
            raise ValueError(msg)
        names = [source.name for source in self.sources]
        if len(names) != len(set(names)):
            msg = "corpus names must be unique"
            raise ValueError(msg)


def _is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def load_manifest(path: Path) -> CorpusManifest:
    """Load a public manifest without resolving or downloading any corpus."""
    return _load(path, expect_private=False)


def load_private_overlay(path: Path) -> CorpusManifest:
    """Load an explicit owner-readable overlay whose identities remain private."""
    if os.name == "nt":
        msg = "private corpus overlays require POSIX owner-only permission semantics"
        raise OSError(msg)
    if is_link_like(path) or not path.is_file():
        msg = "private corpus overlay must be a regular non-symlink file"
        raise ValueError(msg)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        msg = "private corpus overlay must be owner-readable only (chmod 600)"
        raise PermissionError(msg)
    return _load(path, expect_private=True)


def _load(path: Path, *, expect_private: bool) -> CorpusManifest:
    try:
        parsed: object = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        label = "<private-corpus-overlay>" if expect_private else str(path)
        msg = f"could not read corpus manifest {label}"
        if not expect_private:
            msg = f"{msg}: {exc}"
        raise ValueError(msg) from (None if expect_private else exc)
    root = _table(parsed, label="corpus manifest")
    schema = root.get("schema", 1)
    private = root.get("private", False)
    if not isinstance(schema, int) or not isinstance(private, bool):
        msg = "corpus manifest schema/private fields have invalid types"
        raise TypeError(msg)
    if private is not expect_private:
        expected = "private overlay" if expect_private else "public manifest"
        msg = f"expected a {expected}"
        raise ValueError(msg)
    raw_sources = root.get("corpus", [])
    if not _is_object_list(raw_sources):
        msg = "corpus must be an array of tables"
        raise TypeError(msg)
    visibility = CorpusVisibility.PRIVATE if private else CorpusVisibility.PUBLIC
    sources = tuple(_source(_table(item, label="corpus entry"), path, visibility) for item in raw_sources)
    return CorpusManifest(path.resolve(), sources, private, schema)


def _table(value: object, *, label: str) -> dict[str, object]:
    if not _is_object_dict(value):
        msg = f"{label} must be a table"
        raise TypeError(msg)
    table: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            msg = f"{label} contains a non-string key"
            raise TypeError(msg)
        table[key] = item
    return table


def _is_object_dict(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)


def _source(values: dict[str, object], origin: Path, visibility: CorpusVisibility) -> CorpusSource:
    required = {"name", "root", "kind", "digest", "include"}
    missing = sorted(required - values.keys())
    if missing:
        msg = f"corpus entry is missing: {', '.join(missing)}"
        raise ValueError(msg)
    name, root, kind, digest = (values[key] for key in ("name", "root", "kind", "digest"))
    revision = values.get("revision")
    if (
        not isinstance(name, str)
        or not isinstance(root, str)
        or not isinstance(kind, str)
        or not isinstance(digest, str)
    ):
        msg = "corpus name/root/kind/digest must be strings"
        raise TypeError(msg)
    if revision is not None and not isinstance(revision, str):
        msg = "corpus revision must be a string"
        raise TypeError(msg)
    resolved = Path(root)
    if visibility is CorpusVisibility.PUBLIC and resolved.is_absolute():
        msg = "public corpus roots must be relative to the manifest"
        raise ValueError(msg)
    if not resolved.is_absolute():
        if visibility is CorpusVisibility.PUBLIC and ".." in resolved.parts:
            msg = "public corpus roots must stay below the manifest directory"
            raise ValueError(msg)
        resolved = (origin.parent / resolved).resolve()
    return CorpusSource(
        name,
        resolved,
        CorpusKind(kind),
        digest,
        _strings(values["include"], label="corpus include"),
        _strings(values.get("exclude", []), label="corpus exclude"),
        revision,
        visibility,
    )


def _strings(value: object, *, label: str) -> tuple[str, ...]:
    if not _is_object_list(value) or not all(isinstance(item, str) for item in value):
        msg = f"{label} must be an array of strings"
        raise TypeError(msg)
    return tuple(item for item in value if isinstance(item, str))


def merge_manifests(public: CorpusManifest, private: CorpusManifest | None = None) -> CorpusManifest:
    """Combine an optional private overlay without weakening either manifest."""
    if public.private:
        msg = "base corpus manifest must be public"
        raise ValueError(msg)
    if private is None:
        return public
    if not private.private:
        msg = "corpus overlay must be private"
        raise ValueError(msg)
    return CorpusManifest(public.origin, (*public.sources, *private.sources))
