from __future__ import annotations

import re
from typing import TYPE_CHECKING

from repo_standards.core.canonical import scope_digest
from repo_standards.repository import parse_baseline_bytes, parse_manifest_bytes

from sarj_standards.libs.filesystem import is_link_like
from sarj_standards.libs.json_boundary import parse_unique_json


if TYPE_CHECKING:
    from pathlib import Path


PATH = ".repo-standards/baseline.json"
# These releases only introduce and promote the nonbaselineable Makefile rule;
# ordinary finding identities and the existing manifest scope stay compatible.
_COMPATIBLE_TRANSITIONS = frozenset({(18, 19), (18, 20), (19, 20)})
_POLICY_VERSION = re.compile(rb'("policy_version"\s*:\s*)[0-9]+(?=\s*[,}])')


def read_optional(root: Path) -> bytes | None:
    path = root / PATH
    if not path.exists() and not path.is_symlink():
        return None
    if is_link_like(path) or not path.is_file():
        msg = "repository baseline must be a regular file"
        raise OSError(msg)
    return path.read_bytes()


def migrate(contents: bytes, manifest: bytes, *, target_policy_version: int) -> bytes:
    baseline = parse_baseline_bytes(contents)
    configured = parse_manifest_bytes(manifest)
    # Reject duplicate JSON keys before making a textual, metadata-only edit.
    parse_unique_json(contents.decode("utf-8"))
    if baseline.repository_id != configured.repository_id:
        msg = "repository baseline repository_id does not match the planned manifest"
        raise ValueError(msg)
    if baseline.policy_id != "sarj":
        msg = "repository baseline policy must be sarj"
        raise ValueError(msg)
    if baseline.scope_digest != scope_digest(configured):
        msg = "repository baseline scope does not match the planned manifest"
        raise ValueError(msg)
    if baseline.policy_version == target_policy_version:
        return contents
    if (baseline.policy_version, target_policy_version) not in _COMPATIBLE_TRANSITIONS:
        msg = (
            f"repository baseline migration {baseline.policy_version} -> {target_policy_version} "
            "requires a separately reviewed compatibility decision"
        )
        raise ValueError(msg)
    matches = tuple(_POLICY_VERSION.finditer(contents))
    if len(matches) != 1:
        msg = "cannot safely locate the canonical repository baseline policy_version field"
        raise ValueError(msg)
    selected = matches[0]
    return (
        contents[: selected.start()]
        + selected[1]
        + str(target_policy_version).encode("ascii")
        + contents[selected.end() :]
    )
