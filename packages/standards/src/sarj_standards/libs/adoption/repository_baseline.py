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
# Policy 21 changes a baselineable documentation rule's fingerprint version;
# policy 22 adds baselineable PR-template checks. Preserve rejection of these
# transitions rather than silently recapturing or dropping existing debt.
# Policy 26 accepts literal Git paths previously rejected as wildcard syntax.
# Every previously valid manifest scope and finding identity stays unchanged;
# retain all recorded warning/error debt and change only the policy metadata.
# Policy 27 adds a default-disabled local-residue warning. Existing rule
# definitions, fingerprints and scope serialization are unchanged. Explicitly
# enabling it still leaves every new finding unaccepted by the warning ratchet.
# Policy 28 changes operational-script-tests identities; only empty policy 27
# baselines remain compatible. Accepted debt still requires a separate review.
# Policy 29 adds a default-disabled migration warning. Existing finding
# identities and manifest scope remain unchanged; preserve all accepted debt.
# Empty policy 27 baselines may compose the reviewed 27 -> 28 -> 29 steps.
# Policy 30 corrects counts for the opt-in migration warning introduced in 29.
# Policy 28 debt predates that rule and keeps its identities. Empty policy 27
# baselines compose the reviewed 27 -> 28 transition; empty 29 baselines have
# no accepted warning debt to invalidate. Error-only policy 29 baselines also
# exclude that warning; parsing an omitted include_warnings flag means False.
# Nonempty policy 29 warning baselines still require a separate review.
_COMPATIBLE_TRANSITIONS = frozenset({(18, 19), (18, 20), (19, 20), (25, 26), (25, 27), (26, 27), (28, 29), (28, 30)})
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
    transition = (baseline.policy_version, target_policy_version)
    empty_compatible = transition in {(27, 28), (27, 29), (27, 30), (29, 30)} and not baseline.fingerprints
    error_only_compatible = transition == (29, 30) and not baseline.include_warnings
    if transition not in _COMPATIBLE_TRANSITIONS and not empty_compatible and not error_only_compatible:
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
