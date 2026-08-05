"""Reproducible, local-only corpus manifests and snapshots."""

from .manifest import (
    CorpusKind,
    CorpusManifest,
    CorpusSource,
    CorpusVisibility,
    load_manifest,
    load_private_overlay,
    merge_manifests,
)
from .snapshot import CorpusSnapshot, selected_files, snapshot, verify


__all__ = [
    "CorpusKind",
    "CorpusManifest",
    "CorpusSnapshot",
    "CorpusSource",
    "CorpusVisibility",
    "load_manifest",
    "load_private_overlay",
    "merge_manifests",
    "selected_files",
    "snapshot",
    "verify",
]
