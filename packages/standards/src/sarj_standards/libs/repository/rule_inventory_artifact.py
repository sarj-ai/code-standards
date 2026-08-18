from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from typing import Final, TypedDict, TypeGuard

from sarj_standards._meta import CONFIGS_DIR


SCHEMA_VERSION: Final = 1
RULE_INVENTORY_PATH: Final = CONFIGS_DIR / "rule-inventory.v1.json"
_REPOSITORY_INVENTORY_PATH: Final = Path("packages/standards/src/sarj_standards/configs/rule-inventory.v1.json")
_RULE_FIELDS: Final = frozenset({"family", "id", "code", "source", "test"})


@dataclass(frozen=True, slots=True)
class InventorySyncResult:
    status: int
    message: str


class RuleInventoryEntry(TypedDict):
    """One rule's stable runtime-discovery fields."""

    family: str
    id: str
    code: str
    source: str
    test: str


class RuleInventory(TypedDict):
    """The versioned rule inventory shipped with Standards."""

    schemaVersion: int
    rules: list[RuleInventoryEntry]


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def validate(value: object) -> RuleInventory:
    if not _is_object(value) or frozenset(value) != frozenset({"schemaVersion", "rules"}):
        msg = "rule inventory must contain exactly schemaVersion and rules"
        raise ValueError(msg)
    if value["schemaVersion"] != SCHEMA_VERSION:
        msg = f"unsupported rule inventory schemaVersion: {value['schemaVersion']!r}; expected {SCHEMA_VERSION}"
        raise ValueError(msg)
    raw_rules = value["rules"]
    if not _is_array(raw_rules):
        msg = "rule inventory rules must be an array"
        raise ValueError(msg)

    rules = [_validated_rule(rule, index=index) for index, rule in enumerate(raw_rules, start=1)]
    keys = [(rule["family"], rule["id"]) for rule in rules]
    if keys != sorted(keys):
        msg = "rule inventory entries must be sorted by family and id"
        raise ValueError(msg)
    if len(keys) != len(set(keys)):
        msg = "rule inventory contains duplicate family/id entries"
        raise ValueError(msg)
    return {"schemaVersion": SCHEMA_VERSION, "rules": rules}


def _is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _validated_rule(value: object, *, index: int) -> RuleInventoryEntry:
    if not _is_object(value) or frozenset(value) != _RULE_FIELDS:
        msg = f"rule inventory entry {index} must contain exactly: {', '.join(sorted(_RULE_FIELDS))}"
        raise ValueError(msg)

    fields: dict[str, str] = {}
    for field in _RULE_FIELDS:
        item = value[field]
        if not isinstance(item, str) or not item:
            msg = f"rule inventory entry {index} has invalid {field}"
            raise ValueError(msg)
        fields[field] = item

    return {
        "family": fields["family"],
        "id": fields["id"],
        "code": fields["code"],
        "source": _relative_repository_path(fields["source"], field="source", index=index),
        "test": _relative_repository_path(fields["test"], field="test", index=index),
    }


def _relative_repository_path(value: str, *, field: str, index: int) -> str:
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        msg = f"rule inventory entry {index} has invalid {field}: {value!r}"
        raise ValueError(msg)
    return value


def load(path: Path = RULE_INVENTORY_PATH) -> RuleInventory:
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"cannot load shipped rule inventory {path}: {exc}"
        raise ValueError(msg) from exc
    return validate(payload)


def build(root: Path) -> RuleInventory:
    from sarj_standards.libs.repository import rule_maintenance  # ruff: ignore[import-outside-top-level]

    return validate({"schemaVersion": SCHEMA_VERSION, "rules": rule_maintenance.inventory(root)})


def render(root: Path) -> str:
    return (
        json.dumps(
            build(root),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def sync(root: Path, *, check: bool) -> InventorySyncResult:
    from sarj_standards.libs.adoption import transaction  # ruff: ignore[import-outside-top-level]

    destination = root.resolve() / _REPOSITORY_INVENTORY_PATH
    expected = render(root)
    try:
        current = destination.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""

    if current == expected:
        return InventorySyncResult(0, "ok: rule-inventory.v1.json matches live registries")
    if check:
        return InventorySyncResult(
            1,
            "drift: rule-inventory.v1.json differs from live registries; run `sarj-standards maintain rules sync`",
        )
    transaction.atomic_write_text(root.resolve(), destination, expected)
    return InventorySyncResult(0, "updated: rule-inventory.v1.json")
