from __future__ import annotations

from dataclasses import replace
import re
from typing import TYPE_CHECKING

from repo_standards.core.canonical import scope_digest
from repo_standards.repository import (
    RepositoryAnalysisRequest,
    analyze_repository,
    parse_baseline_bytes,
    parse_manifest_bytes,
)

from sarj_standards.libs.filesystem import is_link_like
from sarj_standards.libs.json_boundary import parse_unique_json


if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path


PATH = ".repo-standards/baseline.json"
_COMPATIBLE_TRANSITIONS = frozenset(
    {
        (18, 19),
        (18, 20),
        (19, 20),
        (25, 26),
        (25, 27),
        (26, 27),
        (28, 29),
        (28, 30),
        (30, 31),
        (30, 32),
        (32, 33),
    }
)
_POLICY_VERSION = re.compile(rb'("policy_version"\s*:\s*)[0-9]+(?=\s*[,}])')
_SCOPE_DIGEST = re.compile(rb'("scope_digest"\s*:\s*")[0-9a-f]{64}(?=")')
_FINGERPRINTS = re.compile(rb'("fingerprints"\s*:\s*\[)([^\]]*)(\])')
_IMAGE_POLICY_BASE = 30
_IMAGE_ERROR_POLICY = 32
_MIGRATION_COUNTS_POLICY = 33
_PR_TEMPLATE_POLICY = 34
_MERGE_RISK_POLICY = 35
_TYPED_TOOLING_POLICY = 36


def read_optional(root: Path) -> bytes | None:
    path = root / PATH
    if not path.exists() and not path.is_symlink():
        return None
    if is_link_like(path) or not path.is_file():
        msg = "repository baseline must be a regular file"
        raise OSError(msg)
    return path.read_bytes()


def compatible_policy_change(root: Path, before: bytes, after: bytes) -> bool:
    try:
        configured = (root / ".repo-standards/repository.toml").read_bytes()
        target = parse_baseline_bytes(after).policy_version
        return after == migrate(before, configured, target_policy_version=target)
    except OSError, TypeError, ValueError:
        return False


def retired_fingerprints(root: Path, deleted: Collection[str]) -> frozenset[str]:
    if not deleted or not (root / PATH).is_file():
        return frozenset()
    report = analyze_repository(RepositoryAnalysisRequest(root=root))
    if report.completion != "complete":
        return frozenset()
    return frozenset(item.fingerprint for item in report.diagnostics if item.path in deleted)


def rescope(contents: bytes, previous: bytes, manifest: bytes, retired: Collection[str] = frozenset()) -> bytes:
    contents = _without_fingerprints(contents, frozenset(retired) & set(parse_baseline_bytes(contents).fingerprints))
    baseline = parse_baseline_bytes(contents)
    before = parse_manifest_bytes(previous)
    after = parse_manifest_bytes(manifest)
    digest = scope_digest(after)
    if baseline.scope_digest == digest:
        return contents
    dropped_only = set(after.javascript_artifacts) < set(before.javascript_artifacts) and digest == scope_digest(
        replace(before, javascript_artifacts=after.javascript_artifacts)
    )
    matches = tuple(_SCOPE_DIGEST.finditer(contents))
    if baseline.scope_digest != scope_digest(before) or not dropped_only or len(matches) != 1:
        msg = "repository baseline scope does not match the planned manifest"
        raise ValueError(msg)
    selected = matches[0]
    return contents[: selected.start()] + selected[1] + digest.encode("ascii") + contents[selected.end() :]


def _without_fingerprints(contents: bytes, removed: frozenset[str]) -> bytes:
    if not removed:
        return contents
    matches = tuple(_FINGERPRINTS.finditer(contents))
    if len(matches) != 1:
        msg = "cannot safely locate the canonical repository baseline fingerprints field"
        raise ValueError(msg)
    selected = matches[0]
    items = selected[2].split(b",")
    closing = items[-1][len(items[-1].rstrip()) :]
    kept = [item.rstrip() for item in items if item.strip().strip(b'"').decode("ascii") not in removed]
    body = b",".join(kept) + closing if kept else b""
    return contents[: selected.start()] + selected[1] + body + selected[3] + contents[selected.end() :]


def migrate(contents: bytes, manifest: bytes, *, target_policy_version: int) -> bytes:
    baseline = parse_baseline_bytes(contents)
    configured = parse_manifest_bytes(manifest)
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
    predecessor = {
        53: 49,
        49: 42,
        42: 41,
        41: 40,
        40: 39,
        39: 38,
        38: 37,
        37: _TYPED_TOOLING_POLICY,
        _TYPED_TOOLING_POLICY: _MERGE_RISK_POLICY,
        _MERGE_RISK_POLICY: _PR_TEMPLATE_POLICY,
        _PR_TEMPLATE_POLICY: _MIGRATION_COUNTS_POLICY,
        _MIGRATION_COUNTS_POLICY: _IMAGE_ERROR_POLICY,
    }.get(target_policy_version)
    if predecessor is not None and baseline.policy_version < predecessor:
        intermediate = migrate(contents, manifest, target_policy_version=predecessor)
        return migrate(intermediate, manifest, target_policy_version=target_policy_version)
    if baseline.policy_version < _IMAGE_POLICY_BASE and target_policy_version in {31, 32}:
        intermediate = migrate(contents, manifest, target_policy_version=_IMAGE_POLICY_BASE)
        return migrate(intermediate, manifest, target_policy_version=target_policy_version)
    transition = (baseline.policy_version, target_policy_version)
    empty_compatible = (
        transition
        in {
            (27, 28),
            (27, 29),
            (27, 30),
            (29, 30),
            (31, 32),
            (_MERGE_RISK_POLICY, _TYPED_TOOLING_POLICY),
            (36, 37),
            (37, 38),
            (38, 39),
            (39, 40),
            (40, 41),
            (41, 42),
            (42, 49),
            (49, 53),
        }
        and not baseline.fingerprints
    )
    error_only_compatible = transition in {(29, 30), (31, 32)} and not baseline.include_warnings
    review_policy_absent = configured.pull_request is None or configured.pull_request.review_policy is None
    template_compatible = transition in {(33, 34), (34, 35)} and (not baseline.fingerprints or review_policy_absent)
    if (
        transition not in _COMPATIBLE_TRANSITIONS
        and not empty_compatible
        and not error_only_compatible
        and not template_compatible
    ):
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
