from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
from types import MappingProxyType
from typing import Final

from sarj_standards.libs.adoption import transaction
from sarj_standards.libs.repository import (
    config_generation,
    rule_catalog_artifact,
    rule_inventory_artifact,
    rule_level_source,
    rule_maintenance,
)
from sarj_standards.libs.rules import DefaultLevel, RuleEngine, RuleId, RuleSelector


_INVENTORY_PATH: Final = Path("packages/standards/src/sarj_standards/configs/rule-inventory.v1.json")
_CATALOG_PATH: Final = Path("packages/standards/src/sarj_standards/schemas/rule-catalog.v1.json")
_LEDGER_PATH: Final = Path("packages/standards/src/sarj_standards/configs/rule-ledger.json")
_ESLINT_MANAGED_PATHS: Final = (
    Path("packages/typescript/src/index.ts"),
    Path("packages/standards/src/sarj_standards/configs/eslint.strict.mjs"),
    Path("packages/standards/src/sarj_standards/configs/eslint.application.mjs"),
)
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
    return _set_warning(root, selector, warning=True, check=check)


def promote_error(root: Path, selector: RuleSelector, *, check: bool = False) -> StageResult:
    return _set_warning(root, selector, warning=False, check=check)


def _set_warning(root: Path, selector: RuleSelector, *, warning: bool, check: bool) -> StageResult:
    repository = root.resolve()
    sources = _live_sources(repository)
    if selector not in sources:
        raise ValueError(_unknown_selector_message(selector, set(sources)))

    level = DefaultLevel.WARNING if warning else DefaultLevel.ERROR
    edit = rule_level_source.prepare(repository, selector, sources[selector], level)
    already_staged = edit.current is level
    derived_current = _derived_current(repository) if already_staged else False
    if already_staged and derived_current:
        level = "warning-stage" if warning else "error-level"
        return StageResult(status=0, changed=False, message=f"ok: {selector} is already {level}")
    if check:
        return StageResult(
            status=1,
            changed=False,
            message=_warning_drift_message(selector, warning=warning, already_staged=already_staged),
        )

    managed = (_INVENTORY_PATH, _CATALOG_PATH, _LEDGER_PATH, *_ESLINT_MANAGED_PATHS)
    paths = (edit.path, *(repository / path for path in managed))
    mutation = transaction.FileTransaction.capture(repository, paths)
    try:
        if edit.before != edit.after:
            transaction.atomic_write_text(repository, edit.path, edit.after)
            mutation.mark_written(edit.path)
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
        message=_warning_success_message(selector, warning=warning, already_staged=already_staged),
    )


def _warning_drift_message(selector: RuleSelector, *, warning: bool, already_staged: bool) -> str:
    if already_staged:
        return f"drift: synchronize derived artifacts for {selector}"
    if warning:
        return f"drift: stage {selector} as warning before publication"
    return f"drift: promote {selector} to error"


def _warning_success_message(selector: RuleSelector, *, warning: bool, already_staged: bool) -> str:
    if already_staged:
        return f"synchronized: warning lifecycle and derived artifacts for {selector}"
    if warning:
        return f"staged: {selector} will ship at warning level"
    return f"promoted: {selector} will ship at error level"


def _live_sources(repository: Path) -> dict[RuleSelector, str]:
    inventory = rule_inventory_artifact.build(repository)
    return {
        RuleSelector(_ENGINE_BY_FAMILY[entry["family"]], RuleId(entry["id"])): entry["source"]
        for entry in inventory["rules"]
        if entry["family"] in _ENGINE_BY_FAMILY
    }


def _unknown_selector_message(selector: RuleSelector, known: set[RuleSelector]) -> str:
    requested = str(selector)
    suggestion = get_close_matches(requested, (str(item) for item in known), n=1, cutoff=0.6)
    if suggestion:
        return f"unknown live rule selector: {requested}; did you mean {suggestion[0]}?"
    return f"unknown live rule selector: {requested}; run `code-standards maintain rules manifest` to list selectors"


def _derived_current(repository: Path) -> bool:
    results = (
        rule_inventory_artifact.sync(repository, check=True),
        rule_maintenance.sync_ledger(repository, check=True),
        rule_catalog_artifact.sync(repository, check=True),
    )
    return all(result.status == 0 for result in results) and config_generation.sync_warning_levels(
        repository, check=True
    )


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
    if not config_generation.sync_warning_levels(repository, check=False):  # pragma: no cover - writer returns true.
        msg = "could not synchronize ESLint warning levels"
        raise RuntimeError(msg)
    for path in _ESLINT_MANAGED_PATHS:
        mutation.mark_written(repository / path)
