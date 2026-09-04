from __future__ import annotations

import hashlib
import json
from operator import itemgetter
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, TypedDict

from sarj_standards.libs.release.process import ProcessRunner, run_process


if TYPE_CHECKING:
    from pathlib import Path


SCHEMA_VERSION: Final = 1
_INVENTORY_PATH: Final = "packages/standards/src/sarj_standards/configs/rule-inventory.v1.json"
_CATALOG_PATH: Final = "packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json"
_ENGINE_BY_FAMILY: Final = MappingProxyType(
    {
        "typescript": "eslint",
        "iac": "iac",
        "python": "python",
        "sql": "sql",
        "text": "text",
    }
)
_RELEASE_TARGET_BY_ENGINE: Final = MappingProxyType(
    {
        "eslint": "typescript",
        "iac": "iac",
        "python": "python",
        "sql": "sql",
        "text": "standards",
    }
)
_POLICY_FIELDS: Final = frozenset({"defaultLevel", "optionsSchema"})
_INVENTORY_ENTRY_FIELDS: Final = frozenset({"code", "family", "id", "source", "test"})
_GIT_SHA_LENGTH: Final = 40


class RuleDescriptorV1(TypedDict):
    key: str
    engine: str
    family: str
    id: str
    code: str | None
    defaultLevel: str
    releaseTarget: str
    source: str
    test: str


type ChangeKind = Literal["added", "removed", "implementation-changed", "policy-changed"]
type RuleLevel = Literal["error", "warning"]


class RuleChangeV1(TypedDict):
    kind: ChangeKind
    key: str
    releaseTarget: str
    before: RuleDescriptorV1 | None
    after: RuleDescriptorV1 | None


class RuleChangeSetV1(TypedDict):
    schemaVersion: int
    beforeSha: str
    afterSha: str
    changedSelectors: list[str]
    changeSetDigest: str
    changes: list[RuleChangeV1]


class _RevisionRules(TypedDict):
    descriptors: dict[str, RuleDescriptorV1]
    catalog: dict[str, dict[str, object]]
    implementation_blobs: dict[str, tuple[str, str]]


def compare(
    root: Path,
    *,
    before: str,
    after: str,
    runner: ProcessRunner = run_process,
) -> RuleChangeSetV1:
    resolved = root.resolve()
    before_sha = _resolve_revision(resolved, before, runner=runner)
    after_sha = _resolve_revision(resolved, after, runner=runner)
    old = _load_revision(resolved, before_sha, runner=runner)
    new = _load_revision(resolved, after_sha, runner=runner)
    changes: list[RuleChangeV1] = []
    for key in sorted(old["descriptors"].keys() | new["descriptors"].keys()):
        old_descriptor = old["descriptors"].get(key)
        new_descriptor = new["descriptors"].get(key)
        if old_descriptor is None:
            changes.append(_change("added", key, None, new_descriptor))
            continue
        if new_descriptor is None:
            changes.append(_change("removed", key, old_descriptor, None))
            continue
        old_catalog = old["catalog"][key]
        new_catalog = new["catalog"][key]
        if any(old_catalog.get(field) != new_catalog.get(field) for field in _POLICY_FIELDS):
            changes.append(_change("policy-changed", key, old_descriptor, new_descriptor))
        if (
            _implementation_projection(old_catalog) != _implementation_projection(new_catalog)
            or old["implementation_blobs"][key] != new["implementation_blobs"][key]
        ):
            changes.append(_change("implementation-changed", key, old_descriptor, new_descriptor))
    changes.sort(key=itemgetter("key", "kind"))
    changed_selectors = sorted({change["key"] for change in changes})
    identity: dict[str, object] = {
        "schemaVersion": SCHEMA_VERSION,
        "beforeSha": before_sha,
        "afterSha": after_sha,
        "changedSelectors": changed_selectors,
        "changes": changes,
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "beforeSha": before_sha,
        "afterSha": after_sha,
        "changedSelectors": changed_selectors,
        "changeSetDigest": digest,
        "changes": changes,
    }


def added_rules_at_other_levels(comparison: RuleChangeSetV1, *, required: RuleLevel) -> list[str]:
    return [
        change["key"]
        for change in comparison["changes"]
        if change["kind"] == "added" and change["after"] is not None and change["after"]["defaultLevel"] != required
    ]


def _change(
    kind: ChangeKind,
    key: str,
    before: RuleDescriptorV1 | None,
    after: RuleDescriptorV1 | None,
) -> RuleChangeV1:
    current = after if after is not None else before
    if current is None:  # pragma: no cover - compare only emits changes with at least one descriptor
        msg = "a rule change must contain a before or after descriptor"
        raise ValueError(msg)
    return {
        "kind": kind,
        "key": key,
        "releaseTarget": current["releaseTarget"],
        "before": before,
        "after": after,
    }


def _implementation_projection(rule: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in rule.items() if key not in _POLICY_FIELDS}


def _resolve_revision(root: Path, revision: str, *, runner: ProcessRunner) -> str:
    if not revision:
        msg = "rule comparison revisions must not be empty"
        raise ValueError(msg)
    result = runner(("git", "rev-parse", "--verify", f"{revision}^{{commit}}"), cwd=root, capture_output=True)
    sha = result.stdout.strip()
    if len(sha) != _GIT_SHA_LENGTH or any(character not in "0123456789abcdef" for character in sha):
        msg = f"git did not resolve {revision!r} to a full lowercase commit SHA"
        raise ValueError(msg)
    return sha


def _load_revision(  # ruff: ignore[too-many-locals] -- validates and joins two generated wire artifacts.
    root: Path,
    sha: str,
    *,
    runner: ProcessRunner,
) -> _RevisionRules:
    inventory = _git_json(root, sha, _INVENTORY_PATH, runner=runner)
    catalog = _git_json(root, sha, _CATALOG_PATH, runner=runner)
    inventory_entries = _rules_array(inventory, label="rule inventory")
    catalog_entries = _rules_array(catalog, label="rule catalog")

    inventory_by_key: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(inventory_entries, start=1):
        entry = _object(raw, label=f"rule inventory entry {index}")
        if frozenset(entry) != _INVENTORY_ENTRY_FIELDS:
            msg = f"rule inventory entry {index} has unexpected or missing fields"
            raise ValueError(msg)
        family = _string(entry, "family")
        try:
            engine = _ENGINE_BY_FAMILY[family]
        except KeyError as exc:
            msg = f"rule inventory entry {index} has unknown family {family!r}"
            raise ValueError(msg) from exc
        rule_id = _string(entry, "id")
        key = f"{engine}:{rule_id}"
        if key in inventory_by_key:
            msg = f"rule inventory repeats {key}"
            raise ValueError(msg)
        inventory_by_key[key] = entry

    catalog_by_key: dict[str, dict[str, object]] = {}
    for index, raw in enumerate(catalog_entries, start=1):
        entry = _object(raw, label=f"rule catalog entry {index}")
        key = _string(entry, "key")
        engine = _string(entry, "engine")
        rule_id = _string(entry, "id")
        if key != f"{engine}:{rule_id}" or engine not in _RELEASE_TARGET_BY_ENGINE:
            msg = f"rule catalog entry {index} has inconsistent key/engine/id"
            raise ValueError(msg)
        if key in catalog_by_key:
            msg = f"rule catalog repeats {key}"
            raise ValueError(msg)
        catalog_by_key[key] = entry

    if inventory_by_key.keys() != catalog_by_key.keys():
        missing_catalog = sorted(inventory_by_key.keys() - catalog_by_key.keys())
        missing_inventory = sorted(catalog_by_key.keys() - inventory_by_key.keys())
        msg = (
            "rule inventory/catalog disagreement"
            f"; missing catalog: {', '.join(missing_catalog) or '-'}"
            f"; missing inventory: {', '.join(missing_inventory) or '-'}"
        )
        raise ValueError(msg)

    descriptors: dict[str, RuleDescriptorV1] = {}
    implementation_blobs: dict[str, tuple[str, str]] = {}
    for key in sorted(inventory_by_key):
        inventory_entry = inventory_by_key[key]
        catalog_entry = catalog_by_key[key]
        family = _string(inventory_entry, "family")
        engine = _ENGINE_BY_FAMILY[family]
        catalog_code = catalog_entry.get("code")
        if catalog_code is not None and not isinstance(catalog_code, str):
            msg = f"rule catalog {key} has invalid code"
            raise TypeError(msg)
        inventory_code = _string(inventory_entry, "code")
        if catalog_code is not None and inventory_code != catalog_code:
            msg = f"rule inventory/catalog disagreement for {key}: code differs"
            raise ValueError(msg)
        descriptors[key] = {
            "key": key,
            "engine": engine,
            "family": family,
            "id": _string(inventory_entry, "id"),
            "code": catalog_code,
            "defaultLevel": _string(catalog_entry, "defaultLevel"),
            "releaseTarget": _RELEASE_TARGET_BY_ENGINE[engine],
            "source": _string(inventory_entry, "source"),
            "test": _string(inventory_entry, "test"),
        }
        implementation_blobs[key] = (
            _git_blob_oid(root, sha, descriptors[key]["source"], runner=runner),
            _git_blob_oid(root, sha, descriptors[key]["test"], runner=runner),
        )
    return {
        "descriptors": descriptors,
        "catalog": catalog_by_key,
        "implementation_blobs": implementation_blobs,
    }


def _git_blob_oid(root: Path, sha: str, path: str, *, runner: ProcessRunner) -> str:
    if path.startswith("/") or ".." in path.split("/"):
        msg = f"rule implementation path must be repository-relative: {path!r}"
        raise ValueError(msg)
    result = runner(("git", "rev-parse", "--verify", f"{sha}:{path}"), cwd=root, capture_output=True)
    oid = result.stdout.strip()
    if len(oid) != _GIT_SHA_LENGTH or any(character not in "0123456789abcdef" for character in oid):
        msg = f"git did not resolve rule implementation {path!r} at {sha} to a blob"
        raise ValueError(msg)
    return oid


def _git_json(root: Path, sha: str, path: str, *, runner: ProcessRunner) -> dict[str, object]:
    result = runner(("git", "show", f"{sha}:{path}"), cwd=root, capture_output=True)
    try:
        payload: object = json.loads(result.stdout)  # pyright: ignore[reportAny]
    except json.JSONDecodeError as exc:
        msg = f"{path} at {sha} is not valid JSON"
        raise ValueError(msg) from exc
    return _object(payload, label=path)


def _rules_array(document: dict[str, object], *, label: str) -> list[object]:
    if document.get("schemaVersion") != 1 or set(document) != {"schemaVersion", "rules"}:
        msg = f"{label} must contain exactly schemaVersion 1 and rules"
        raise ValueError(msg)
    rules = document["rules"]
    if not isinstance(rules, list):
        msg = f"{label} rules must be an array"
        raise TypeError(msg)
    return rules  # pyright: ignore[reportUnknownVariableType]


def _object(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        msg = f"{label} must be an object"
        raise TypeError(msg)
    if not all(isinstance(key, str) for key in value):  # pyright: ignore[reportUnknownVariableType]
        msg = f"{label} must have string keys"
        raise TypeError(msg)
    return value  # pyright: ignore[reportUnknownVariableType]


def _string(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        msg = f"rule field {key} must be a non-empty string"
        raise TypeError(msg)
    return item


def render_text(result: RuleChangeSetV1) -> str:
    lines = [f"rules {result['beforeSha']}..{result['afterSha']}"]
    lines.extend(f"{item['kind']}: {item['key']}" for item in result["changes"])
    if not result["changes"]:
        lines.append("no rule changes")
    return "\n".join(lines)
