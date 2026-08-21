from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from operator import itemgetter
import os
from pathlib import Path
import re
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import] -- fixed read-only git argv.
from typing import TYPE_CHECKING, TypeIs

from sarj_standards.libs.filesystem import is_link_like


if TYPE_CHECKING:
    from collections.abc import Iterable

    from .models import Diagnostic


SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
_MAX_BYTES = 16 * 1024 * 1024
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_NON_BASELINEABLE_SOURCES = frozenset({"react-doctor"})
_HUNK = re.compile(r"^@@ -(?:\d+)(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True, slots=True)
class ChangedLineScope:
    paths: frozenset[str]
    lines: dict[str, frozenset[int]]
    failed: bool = False


def changed_line_scope(root: Path, *, staged: bool) -> ChangedLineScope | None:
    base = os.environ.get("SARJ_STANDARDS_BASE", "").strip()  # ruff: ignore[banned-api]
    if not staged and not base:
        return None
    if not staged and _GIT_SHA.fullmatch(base) is None:
        return ChangedLineScope(frozenset(), {}, failed=True)
    git = shutil.which("git")
    if git is None:
        return ChangedLineScope(frozenset(), {}, failed=True)
    comparison = ("--cached",) if staged else (f"{base}...HEAD",)
    common = (git, "diff", *comparison, "--diff-filter=ACMR")
    names = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (*common, "--name-only", "-z", "--"), cwd=root, check=False, text=True, capture_output=True
    )
    patch = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        (*common, "--unified=0", "--no-color", "--no-ext-diff", "--"),
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
    )
    if names.returncode != 0 or patch.returncode != 0:
        return ChangedLineScope(frozenset(), {}, failed=True)
    paths = frozenset(item for item in names.stdout.split("\0") if item)
    parsed: dict[str, set[int]] = {}
    current = ""
    for line in patch.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            parsed.setdefault(current, set())
            continue
        match = _HUNK.match(line)
        if not current or match is None:
            continue
        start = int(match.group(1))
        count = 1 if match.group(2) is None else int(match.group(2))
        parsed[current].update(range(start, start + count))
    return ChangedLineScope(paths, {path: frozenset(lines) for path, lines in parsed.items()})


def touches_changed_lines(diagnostic: Diagnostic, scope: ChangedLineScope | None) -> bool:
    if scope is None:
        return False
    if scope.failed:
        return True
    path = diagnostic.location.path
    if path not in scope.paths:
        return False
    changed = scope.lines.get(path)
    if not changed:
        return True
    location = diagnostic.location
    if location.region is not None:
        start = location.region.start.line + 1
        end = location.region.end.line + 1
        return any(line in changed for line in range(start, end + 1))
    if location.position is not None:
        return location.position.line + 1 in changed
    return True


def is_baselineable(diagnostic: Diagnostic) -> bool:
    return diagnostic.source not in _NON_BASELINEABLE_SOURCES


def load(
    path: Path,
    *,
    require_v2: bool = False,
    expected_bundle_version: str | None = None,
    expected_catalog_digest: str | None = None,
) -> dict[str, int]:
    if not path.is_file() or is_link_like(path):
        msg = f"diagnostic baseline must be a regular file: {path}"
        raise ValueError(msg)
    if path.stat().st_size > _MAX_BYTES:
        msg = f"diagnostic baseline exceeds {_MAX_BYTES} bytes: {path}"
        raise ValueError(msg)
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        msg = f"cannot read diagnostic baseline {path}: {exc}"
        raise ValueError(msg) from exc
    root = _string_object_dict(parsed, label="diagnostic baseline")
    schema_version = root.get("schemaVersion")
    if schema_version not in {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION}:
        msg = f"diagnostic baseline schemaVersion must equal {LEGACY_SCHEMA_VERSION} or {SCHEMA_VERSION}"
        raise ValueError(msg)
    if require_v2 and schema_version != SCHEMA_VERSION:
        msg = "diagnostic baseline must use schemaVersion 2; run `code-standards baseline update`"
        raise ValueError(msg)
    if schema_version == SCHEMA_VERSION:
        provenance = _validate_provenance(root.get("provenance"))
        if expected_bundle_version is not None and provenance["bundleVersion"] != expected_bundle_version:
            msg = "diagnostic baseline bundle version does not match the executing Standards bundle"
            raise ValueError(msg)
        if expected_catalog_digest is not None and provenance["catalogDigest"] != expected_catalog_digest:
            msg = "diagnostic baseline policy digest does not match the executing Standards bundle"
            raise ValueError(msg)
    entries = root.get("diagnostics")
    if not _is_object_list(entries):
        msg = "diagnostic baseline diagnostics must be a list"
        raise TypeError(msg)
    fingerprints: dict[str, int] = {}
    for index, value in enumerate(entries):
        entry = _string_object_dict(value, label=f"diagnostic baseline entry {index}")
        fingerprint = entry.get("fingerprint")
        if not isinstance(fingerprint, str) or _FINGERPRINT.fullmatch(fingerprint) is None:
            msg = f"diagnostic baseline entry {index} has an invalid fingerprint"
            raise ValueError(msg)
        _ = _required_text(entry, "source", index)
        _ = _required_text(entry, "ruleId", index)
        relative = _required_text(entry, "path", index)
        count = entry.get("count")
        if type(count) is not int or count < 1:
            msg = f"diagnostic baseline entry {index} count must be a positive integer"
            raise ValueError(msg)
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            msg = f"diagnostic baseline entry {index} path must be repository-relative"
            raise ValueError(msg)
        if fingerprint in fingerprints:
            msg = f"diagnostic baseline repeats fingerprint: {fingerprint}"
            raise ValueError(msg)
        fingerprints[fingerprint] = count
    return fingerprints


def _required_text(entry: dict[str, object], key: str, index: int) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        msg = f"diagnostic baseline entry {index} requires a non-empty {key}"
        raise TypeError(msg)
    return value


def render(
    diagnostics: Iterable[Diagnostic],
    *,
    bundle_version: str | None = None,
    consumer_base_sha: str | None = None,
    catalog_digest: str | None = None,
) -> str:
    entries = _diagnostic_entries(diagnostics)
    payload: dict[str, object] = {"schemaVersion": LEGACY_SCHEMA_VERSION, "diagnostics": entries}
    provenance = (bundle_version, consumer_base_sha, catalog_digest)
    if any(value is not None for value in provenance):
        if not all(isinstance(value, str) and value for value in provenance):
            msg = "diagnostic baseline provenance requires bundle version, consumer base SHA, and catalog digest"
            raise ValueError(msg)
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "provenance": {
                "bundleVersion": bundle_version,
                "consumerBaseSha": consumer_base_sha,
                "catalogDigest": catalog_digest,
            },
            "diagnostics": entries,
        }
        _validate_provenance(payload["provenance"])
    return json.dumps(payload, indent=2) + "\n"


def merge_scoped(
    path: Path,
    diagnostics: Iterable[Diagnostic],
    *,
    selectors: Iterable[str],
    bundle_version: str,
    consumer_base_sha: str,
    catalog_digest: str,
) -> str:
    selected = frozenset(selectors)
    if not selected:
        msg = "a scoped baseline merge requires at least one promoted selector"
        raise ValueError(msg)
    _ = load(path)
    parsed: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    root = _string_object_dict(parsed, label="diagnostic baseline")
    current = root.get("diagnostics")
    if not _is_object_list(current):
        msg = "diagnostic baseline diagnostics must be a list"
        raise TypeError(msg)
    preserved = [
        entry
        for value in current
        if not _entry_selected(entry := _string_object_dict(value, label="diagnostic baseline entry"), selected)
    ]
    replacement = [entry for entry in _diagnostic_entries(diagnostics) if _entry_selected(entry, selected)]
    combined = sorted((*preserved, *replacement), key=itemgetter("source", "ruleId", "path", "fingerprint"))
    payload: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "provenance": {
            "bundleVersion": bundle_version,
            "consumerBaseSha": consumer_base_sha,
            "catalogDigest": catalog_digest,
        },
        "diagnostics": combined,
    }
    _validate_provenance(payload["provenance"])
    return json.dumps(payload, indent=2) + "\n"


def _diagnostic_entries(diagnostics: Iterable[Diagnostic]) -> list[dict[str, object]]:
    entries: dict[str, dict[str, object]] = {}
    for item in diagnostics:
        if item.fingerprint is None or not is_baselineable(item):
            continue
        entry = entries.setdefault(
            item.fingerprint,
            {
                "fingerprint": item.fingerprint,
                "source": item.source,
                "ruleId": item.rule_id or item.code,
                "path": item.location.path,
                "count": 0,
            },
        )
        count = entry["count"]
        if not isinstance(count, int):
            msg = "diagnostic baseline count has an invalid internal type"
            raise TypeError(msg)
        entry["count"] = count + 1
    return sorted(
        entries.values(),
        key=itemgetter("source", "ruleId", "path", "fingerprint"),
    )


def _entry_selected(entry: dict[str, object], selectors: frozenset[str]) -> bool:
    source = entry.get("source")
    rule_id = entry.get("ruleId")
    return (
        isinstance(source, str)
        and isinstance(rule_id, str)
        and (rule_id in selectors or f"{source}:{rule_id}" in selectors)
    )


def _validate_provenance(value: object) -> dict[str, str]:
    provenance = _string_object_dict(value, label="diagnostic baseline provenance")
    if set(provenance) != {"bundleVersion", "consumerBaseSha", "catalogDigest"}:
        msg = "diagnostic baseline provenance has invalid fields"
        raise ValueError(msg)
    _ = _required_text(provenance, "bundleVersion", 0)
    base = _required_text(provenance, "consumerBaseSha", 0)
    digest = _required_text(provenance, "catalogDigest", 0)
    if _GIT_SHA.fullmatch(base) is None or _FINGERPRINT.fullmatch(digest) is None:
        msg = "diagnostic baseline provenance requires SHA-256-shaped base and catalog digests"
        raise ValueError(msg)
    bundle = provenance["bundleVersion"]
    if not isinstance(bundle, str):
        msg = "diagnostic baseline bundle version must be text"
        raise TypeError(msg)
    return {"bundleVersion": bundle, "consumerBaseSha": base, "catalogDigest": digest}


def repository_base_sha(root: Path) -> str:
    explicit = os.environ.get("SARJ_STANDARDS_BASE", "").strip()  # ruff: ignore[banned-api]
    if _GIT_SHA.fullmatch(explicit) is not None:
        return explicit
    git = shutil.which("git")
    if git is None:
        return "0" * 40
    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] -- fixed read-only Git argv.
        (git, "rev-parse", "HEAD"), cwd=root, check=False, text=True, capture_output=True, shell=False
    )
    candidate = result.stdout.strip()
    if _GIT_SHA.fullmatch(candidate) is None:
        # A baseline may be initialized before the consumer's first commit.
        # The all-zero object ID is an explicit "no commit yet" sentinel; a
        # rollout replaces it with the captured immutable base SHA.
        return "0" * 40
    return candidate


def bundled_catalog_digest() -> str:
    configs = Path(__file__).parents[2] / "configs"
    digest = sha256()
    for path in sorted(item for item in configs.rglob("*") if item.is_file()):
        digest.update(path.relative_to(configs).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _string_object_dict(value: object, *, label: str) -> dict[str, object]:
    if not _is_object_dict(value):
        msg = f"{label} must be an object"
        raise TypeError(msg)
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            msg = f"{label} contains a non-string key"
            raise TypeError(msg)
        result[key] = item
    return result


def _is_object_dict(value: object) -> TypeIs[dict[object, object]]:
    return isinstance(value, dict)


def _is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


__all__ = [
    "SCHEMA_VERSION",
    "bundled_catalog_digest",
    "changed_line_scope",
    "is_baselineable",
    "load",
    "merge_scoped",
    "render",
    "repository_base_sha",
    "touches_changed_lines",
]
