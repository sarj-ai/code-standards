from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
import json
from pathlib import Path
from types import MappingProxyType
from typing import Final, TypeGuard

from sarj_standards.libs.adoption import transaction
from sarj_standards.libs.repository import rule_catalog_artifact, rule_inventory_artifact, rule_maintenance
from sarj_standards.libs.rules import RuleEngine, RuleId, RuleSelector


_WARNING_PATH: Final = Path("packages/standards/src/sarj_standards/configs/rule-warning-levels.v1.json")
_INVENTORY_PATH: Final = Path("packages/standards/src/sarj_standards/configs/rule-inventory.v1.json")
_CATALOG_PATH: Final = Path("packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json")
_LEDGER_PATH: Final = Path("packages/standards/src/sarj_standards/configs/rule-ledger.json")
_ENGINE_BY_FAMILY: Final = MappingProxyType(
    {
        "typescript": RuleEngine.ESLINT,
        "iac": RuleEngine.IAC,
        "python": RuleEngine.PYTHON,
        "sql": RuleEngine.SQL,
        "text": RuleEngine.TEXT,
    }
)


@dataclass(frozen=True, slots=True)
class StageResult:
    status: int
    changed: bool
    message: str


def stage_warning(root: Path, selector: RuleSelector, *, check: bool = False) -> StageResult:
    repository = root.resolve()
    inventory = rule_inventory_artifact.build(repository)
    known = {
        RuleSelector(_ENGINE_BY_FAMILY[entry["family"]], RuleId(entry["id"]))
        for entry in inventory["rules"]
        if entry["family"] in _ENGINE_BY_FAMILY
    }
    if selector not in known:
        raise ValueError(_unknown_selector_message(selector, known))

    # Building before mutation proves source-owned metadata/examples are complete.
    _ = rule_catalog_artifact.build(repository)
    warning_path = repository / _WARNING_PATH
    selected = set(_load(warning_path))
    already_staged = selector in selected
    selected.add(selector)
    rendered = _render(selected)
    warning_current = warning_path.read_text(encoding="utf-8") == rendered
    derived_current = _derived_current(repository) if already_staged and warning_current else False
    if already_staged and warning_current and derived_current:
        return StageResult(status=0, changed=False, message=f"ok: {selector} is already warning-stage")
    if check:
        return StageResult(
            status=1,
            changed=False,
            message=(
                f"drift: synchronize derived artifacts for warning-stage {selector}"
                if already_staged
                else f"drift: stage {selector} as warning before publication"
            ),
        )

    managed = (_WARNING_PATH, _INVENTORY_PATH, _CATALOG_PATH, _LEDGER_PATH)
    paths = tuple(repository / path for path in managed)
    mutation = transaction.FileTransaction.capture(repository, paths)
    try:
        if not warning_current:
            transaction.atomic_write_text(repository, warning_path, rendered)
            mutation.mark_written(warning_path)
        _synchronize(repository, mutation)
    except BaseException:
        rollback = mutation.rollback()
        if not rollback.ok:
            msg = rollback.render() or "rule lifecycle rollback was incomplete"
            raise RuntimeError(msg) from None
        raise
    return StageResult(
        status=0,
        changed=True,
        message=(
            f"synchronized: warning lifecycle and derived artifacts for {selector}"
            if already_staged
            else f"staged: {selector} will ship at warning level"
        ),
    )


def _render(selectors: set[RuleSelector]) -> str:
    return (
        json.dumps(
            {"schemaVersion": 1, "rules": sorted(str(item) for item in selectors)},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )


def _unknown_selector_message(selector: RuleSelector, known: set[RuleSelector]) -> str:
    requested = str(selector)
    suggestion = get_close_matches(requested, (str(item) for item in known), n=1, cutoff=0.6)
    if suggestion:
        return f"unknown live rule selector: {requested}; did you mean {suggestion[0]}?"
    return f"unknown live rule selector: {requested}; run `sarj-standards maintain rules manifest` to list selectors"


def _derived_current(repository: Path) -> bool:
    results = (
        rule_inventory_artifact.sync(repository, check=True),
        rule_maintenance.sync_ledger(repository, check=True),
        rule_catalog_artifact.sync(repository, check=True),
    )
    return all(result.status == 0 for result in results)


def _synchronize(repository: Path, mutation: transaction.FileTransaction) -> None:
    operations = (
        (rule_maintenance.sync_ledger, repository / _LEDGER_PATH),
        (rule_inventory_artifact.sync, repository / _INVENTORY_PATH),
        (rule_catalog_artifact.sync, repository / _CATALOG_PATH),
    )
    for operation, path in operations:
        result = operation(repository, check=False)
        mutation.mark_written(path)
        if result.status != 0:
            msg = f"could not synchronize derived rule artifact: {path}"
            raise RuntimeError(msg)


def _load(path: Path) -> tuple[RuleSelector, ...]:
    payload: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    if not _is_object(payload):
        msg = "rule warning lifecycle must contain exactly schemaVersion and rules"
        raise TypeError(msg)
    if set(payload) != {"schemaVersion", "rules"}:
        msg = "rule warning lifecycle must contain exactly schemaVersion and rules"
        raise ValueError(msg)
    rules = payload.get("rules")
    if payload.get("schemaVersion") != 1 or not _is_array(rules):
        msg = "rule warning lifecycle must use schemaVersion 1 and a rules array"
        raise ValueError(msg)
    values = rules
    if any(not isinstance(value, str) or not value for value in values):
        msg = "rule warning lifecycle must contain unique non-empty selectors"
        raise ValueError(msg)
    selectors = tuple(RuleSelector.parse(value) for value in values if isinstance(value, str))
    if len(set(selectors)) != len(selectors):
        msg = "rule warning lifecycle must contain unique non-empty selectors"
        raise ValueError(msg)
    return selectors


def _is_object(value: object) -> TypeGuard[dict[str, object]]:
    # JSON object keys are strings by definition.
    return isinstance(value, dict)


def _is_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)
