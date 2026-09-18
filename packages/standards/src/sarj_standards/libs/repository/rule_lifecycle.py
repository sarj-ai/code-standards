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
    rule_maintenance,
)
from sarj_standards.libs.rules import RuleEngine, RuleId, RuleSelector, warning_levels


_WARNING_PATH: Final = Path("packages/standards/src/sarj_standards/configs/rule-warning-levels.v1.json")
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
    known = _known_selectors(repository)
    if selector not in known:
        raise ValueError(_unknown_selector_message(selector, known))

    warning_path = repository / _WARNING_PATH
    selected = set(warning_levels.load(warning_path))
    already_staged = _update_warning_selection(selected, selector, warning=warning)
    rendered = warning_levels.render(selected)
    warning_current = warning_path.read_text(encoding="utf-8") == rendered
    derived_current = _derived_current(repository) if already_staged and warning_current else False
    if already_staged and warning_current and derived_current:
        level = "warning-stage" if warning else "error-level"
        return StageResult(status=0, changed=False, message=f"ok: {selector} is already {level}")
    if check:
        return StageResult(
            status=1,
            changed=False,
            message=_warning_drift_message(selector, warning=warning, already_staged=already_staged),
        )

    managed = (_WARNING_PATH, _INVENTORY_PATH, _CATALOG_PATH, _LEDGER_PATH, *_ESLINT_MANAGED_PATHS)
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
        message=_warning_success_message(selector, warning=warning, already_staged=already_staged),
    )


def _update_warning_selection(selected: set[RuleSelector], selector: RuleSelector, *, warning: bool) -> bool:
    if not warning:
        selected.difference_update(_alias_selectors(selector))
    already_staged = (selector in selected) is warning
    if warning:
        selected.add(selector)
    else:
        selected.discard(selector)
    return already_staged


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


def _known_selectors(repository: Path) -> set[RuleSelector]:
    inventory = rule_inventory_artifact.build(repository)
    return {
        RuleSelector(_ENGINE_BY_FAMILY[entry["family"]], RuleId(entry["id"]))
        for entry in inventory["rules"]
        if entry["family"] in _ENGINE_BY_FAMILY
    }


def _alias_selectors(selector: RuleSelector) -> set[RuleSelector]:
    if selector.engine is not RuleEngine.PYTHON:
        return set()
    from sarj_python_lint.rules import REGISTRY  # ruff: ignore[import-outside-top-level]

    rule = REGISTRY.get(str(selector.rule_id))
    documentation = None if rule is None else rule.documentation
    aliases = () if documentation is None else documentation.aliases
    return {RuleSelector(selector.engine, RuleId(alias)) for alias in aliases}


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
    if not config_generation.sync_warning_levels(repository, check=False):  # pragma: no cover - writer returns true.
        msg = "could not synchronize ESLint warning levels"
        raise RuntimeError(msg)
    for path in _ESLINT_MANAGED_PATHS:
        mutation.mark_written(repository / path)
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
