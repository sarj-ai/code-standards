"""Rule inventory, promotion, and ledger maintenance."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import json
from operator import itemgetter
import re
from typing import TYPE_CHECKING, Final, Protocol

from sarj_lint_configs.libs.adoption.manifest import as_table, list_field
from sarj_lint_configs.libs.linting import textlint

from . import repository


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


_FAMILIES: Final = (
    ("python", "sarj_python_lint.rules", "packages/python"),
    ("sql", "sarj_sql_lint.rules", "packages/sql"),
    ("iac", "sarj_iac_lint.rules", "packages/iac"),
)
_RENAME_ENTRY: Final = re.compile(r'^\s*"(?P<old>[a-z0-9-]+)": "(?P<new>[a-z0-9-]+)",', re.MULTILINE)
_PLACEHOLDER: Final = "TODO: say why it went, in one line a consumer can act on"


class Rule(Protocol):
    code: str
    __module__: str


@dataclass(frozen=True, slots=True)
class SyncResult:
    status: int
    message: str


def inventory(root: Path) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for family, module_name, package in _FAMILIES:
        registry = _registry(module_name)
        for rule_id, rule in sorted(registry.items()):
            module = rule.__module__.replace(".", "/")
            source_name = module.rsplit("/", 1)[-1]
            items.append(
                {
                    "family": family,
                    "id": rule_id,
                    "code": str(rule.code),
                    "source": f"{package}/src/{module}.py",
                    "test": f"{package}/tests/rules/test_{source_name}.py",
                }
            )
    for rule_id, meta in sorted(textlint.REGISTRY.items()):
        items.append(
            {
                "family": "text",
                "id": rule_id,
                "code": meta.code,
                "source": "packages/lint-configs/src/sarj_lint_configs/textlint.py",
                "test": "packages/lint-configs/tests/test_textlint.py",
            }
        )
    items.extend(
        {
            "family": "typescript",
            "id": rule_id,
            "code": f"@sarj/{rule_id}",
            "source": f"packages/typescript/src/rules/{rule_id}.ts",
            "test": f"packages/typescript/tests/rules/{rule_id}.test.ts",
        }
        for rule_id in repository.eslint_rule_names(root)
    )
    return sorted(items, key=itemgetter("family", "id"))


def sync_ledger(root: Path, *, check: bool) -> SyncResult:
    path = root / "packages/lint-configs/src/sarj_lint_configs/configs/rule-ledger.json"
    previous = _load_ledger(path)
    rules: dict[str, list[str]] = {"eslint": repository.eslint_rule_names(root)}
    codes: dict[str, list[str]] = {}
    for family, module_name, _package in _FAMILIES:
        registry = _registry(module_name)
        rules[family] = sorted(registry)
        codes[family] = sorted(str(rule.code) for rule in registry.values())
    rules["text"] = sorted(textlint.REGISTRY)
    codes["text"] = sorted(meta.code for meta in textlint.REGISTRY.values())
    retired = _retired(previous, root)
    known = {str(entry.get("id")) for entry in retired}
    old_rules = repository_table(previous.get("rules"))
    old_codes = repository_table(previous.get("codes"))
    for family, raw_names in old_rules.items():
        prefix = "@sarj/" if family == "eslint" else ""
        for name in _string_list(raw_names):
            identifier = f"{prefix}{name}"
            if name not in rules.get(family, []) and identifier not in known:
                retired.append(_retired_entry(identifier, family))
                known.add(identifier)
    for family, raw_codes in old_codes.items():
        for code in _string_list(raw_codes):
            if code not in codes.get(family, []) and code not in known:
                retired.append(_retired_entry(code, "code"))
                known.add(code)
    updated = {
        "$comment": previous.get("$comment", "Rule compatibility ledger."),
        "rules": rules,
        "codes": codes,
        "retired": sorted(retired, key=lambda entry: str(entry.get("id"))),
    }
    rendered = json.dumps(updated, indent=2) + "\n"
    current = path.read_text(encoding="utf-8")
    if rendered == current:
        return SyncResult(0, f"ok: {path.name} matches the registries")
    if check:
        return SyncResult(1, f"drift: {path}")
    path.write_text(rendered, encoding="utf-8")
    status = 1 if any(entry.get("note") == _PLACEHOLDER for entry in retired) else 0
    return SyncResult(status, f"wrote: {path}")


def repository_table(value: object) -> dict[str, object]:
    return as_table(value)


def _load_ledger(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))  # pyright: ignore[reportAny]
    return repository_table(value)


def _registry(module_name: str) -> Mapping[str, type[Rule]]:
    module = import_module(module_name)
    value = getattr(module, "REGISTRY", None)
    if not isinstance(value, dict):
        msg = f"{module_name} has no registry"
        raise TypeError(msg)
    return value  # pyright: ignore[reportUnknownVariableType]


def _retired(previous: Mapping[str, object], root: Path) -> list[dict[str, object]]:
    entries = [repository_table(item) for item in _object_list(previous.get("retired"))]
    kept = [entry for entry in entries if not (entry.get("kind") == "eslint" and entry.get("status") == "renamed")]
    existing = {str(entry.get("id")): entry for entry in entries}
    renames_path = root / "packages/typescript/src/rules/_renames.ts"
    for match in _RENAME_ENTRY.finditer(renames_path.read_text(encoding="utf-8")):
        old = match.group("old")
        new = match.group("new")
        identifier = f"@sarj/{old}"
        replacement = f"@sarj/{new}"
        prior = existing.get(identifier)
        kept.append(
            prior
            if prior is not None and prior.get("replacement") == replacement
            else {
                "id": identifier,
                "kind": "eslint",
                "status": "renamed",
                "replacement": replacement,
                "note": f"Replace @sarj/{old} with @sarj/{new} before upgrading.",
            }
        )
    return kept


def _retired_entry(identifier: str, kind: str) -> dict[str, object]:
    return {"id": identifier, "kind": kind, "status": "removed", "replacement": None, "note": _PLACEHOLDER}


def _object_list(value: object) -> list[object]:
    return list_field({"value": value}, "value")


def _string_list(value: object) -> list[str]:
    return [item for item in _object_list(value) if isinstance(item, str)]
