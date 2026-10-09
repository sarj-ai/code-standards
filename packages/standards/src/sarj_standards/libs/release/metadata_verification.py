from __future__ import annotations

import re
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- catches failures from the argv-only runner.
import tomllib
from typing import TYPE_CHECKING, TypeGuard

from sarj_standards.libs.json_boundary import parse_json


if TYPE_CHECKING:
    from pathlib import Path

    from sarj_standards.libs.release.rollout import CommandRunner


_MANIFEST = ".sarj-standards.toml"
_PROVENANCE = frozenset({"bundleVersion", "consumerBaseSha", "catalogDigest"})
_RAW_DIFF_FIELDS = 5


def metadata_only_rollout(
    repo: Path, runner: CommandRunner, *, base_sha: str, version: str, baseline_path: Path | None
) -> bool:
    if re.fullmatch(r"[0-9a-f]{40}", base_sha) is None:
        return False
    try:
        return _metadata_only_candidate(repo, runner, base_sha=base_sha, version=version, baseline_path=baseline_path)
    except OSError, ValueError, subprocess.SubprocessError:
        # An unavailable base, malformed document or unknown shape uses the full gate.
        return False


def _metadata_only_candidate(
    repo: Path, runner: CommandRunner, *, base_sha: str, version: str, baseline_path: Path | None
) -> bool:
    baseline = baseline_path.relative_to(repo).as_posix() if baseline_path is not None else ""
    status = runner.run(("git", "status", "--porcelain", "--untracked-files=all"), cwd=repo)
    if status.stdout:
        return False
    diff = runner.run(
        ("git", "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--raw", "-z", base_sha, "HEAD"),
        cwd=repo,
    )
    paths = _regular_metadata_changes(diff.stdout, baseline)
    if paths is None or _MANIFEST not in paths:
        return False
    before = _manifest(_blob(repo, runner, base_sha, _MANIFEST))
    after = _manifest(_blob(repo, runner, "HEAD", _MANIFEST))
    previous_version = before.pop("bundle", None)
    target_version = after.pop("bundle", None)
    if not isinstance(previous_version, str) or previous_version == version or target_version != version:
        return False
    if not _identical(before, after):
        return False
    return baseline not in paths or _baseline_metadata(
        before_text=_blob(repo, runner, base_sha, baseline),
        after_text=_blob(repo, runner, "HEAD", baseline),
        base_sha=base_sha,
        previous_version=previous_version,
        version=version,
    )


def _regular_metadata_changes(raw: str, baseline: str) -> set[str] | None:
    records = raw.removesuffix("\0").split("\0")
    if len(records) % 2:
        return None
    paths: set[str] = set()
    for header, path in zip(records[::2], records[1::2], strict=True):
        fields = header.split()
        if len(fields) != _RAW_DIFF_FIELDS or fields[0] != ":100644" or fields[1] != "100644" or fields[-1] != "M":
            return None
        if path not in {_MANIFEST, baseline}:
            return None
        paths.add(path)
    return paths


def _blob(repo: Path, runner: CommandRunner, revision: str, path: str) -> str:
    return runner.run(("git", "cat-file", "blob", f"{revision}:{path}"), cwd=repo).stdout


def _manifest(text: str) -> dict[str, object]:
    value: object = tomllib.loads(text)
    if not _object(value):
        msg = "invalid manifest"
        raise ValueError(msg)
    return value


def _baseline_metadata(
    *, before_text: str, after_text: str, base_sha: str, previous_version: str, version: str
) -> bool:
    before, after = parse_json(before_text), parse_json(after_text)
    if not _object(before) or not _object(after):
        return False
    previous, current = before.pop("provenance", None), after.pop("provenance", None)
    if not _identical(before, after) or not _object(previous) or not _object(current):
        return False
    if set(previous) != _PROVENANCE or set(current) != _PROVENANCE:
        return False
    digest = current.get("catalogDigest")
    return (
        previous.get("bundleVersion") == previous_version
        and current.get("bundleVersion") == version
        and current.get("consumerBaseSha") == base_sha
        and isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
    )


def _object(value: object) -> TypeGuard[dict[str, object]]:
    return _mapping(value) and all(isinstance(key, str) for key in value)


def _mapping(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def _identical(before: object, after: object) -> bool:
    if type(before) is not type(after):
        return False
    if _object(before) and _object(after):
        return before.keys() == after.keys() and all(_identical(value, after[key]) for key, value in before.items())
    if _array(before) and _array(after):
        return len(before) == len(after) and all(map(_identical, before, after, strict=True))
    return before == after


def _array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)
