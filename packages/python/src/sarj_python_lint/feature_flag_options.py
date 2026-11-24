from __future__ import annotations

from dataclasses import dataclass
import re
import tomllib
from typing import TYPE_CHECKING, Final, TypeGuard, final


if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


MANIFEST_NAME: Final = ".sarj-standards.toml"
ENGINE_TABLE: Final = "python"
RULE_TABLE: Final = "no-retained-feature-flag"
DEFAULT_PROCESS_STATE: Final = ("app.state",)

_LABEL: Final = f"manifest [{ENGINE_TABLE}.{RULE_TABLE}]"
_IDENTIFIER: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DOTTED: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_REQUIRED: Final = ("modules", "snapshot_types")
_IDENTIFIER_KEYS: Final = ("snapshot_types", "resolver_functions", "resolver_methods", "selector_methods")
_DOTTED_KEYS: Final = ("modules", "startup_functions", "unit_of_work_types", "memoizers", "process_state")
_MAX_ANCESTORS: Final = 24


@dataclass(frozen=True, slots=True)
class FeatureFlagOptions:
    modules: tuple[str, ...]
    snapshot_types: tuple[str, ...]
    resolver_functions: tuple[str, ...] = ()
    resolver_methods: tuple[str, ...] = ()
    selector_methods: tuple[str, ...] = ()
    startup_functions: tuple[str, ...] = ()
    unit_of_work_types: tuple[str, ...] = ()
    memoizers: tuple[str, ...] = ()
    process_state: tuple[str, ...] = DEFAULT_PROCESS_STATE

    def owns_module(self, module: str) -> bool:
        return any(module == owner or module.startswith(f"{owner}.") for owner in self.modules)

    def manifest_fields(self) -> dict[str, tuple[str, ...]]:
        optional = {
            "resolver_functions": self.resolver_functions,
            "resolver_methods": self.resolver_methods,
            "selector_methods": self.selector_methods,
            "startup_functions": self.startup_functions,
            "unit_of_work_types": self.unit_of_work_types,
            "memoizers": self.memoizers,
        }
        fields = {"modules": self.modules, "snapshot_types": self.snapshot_types}
        fields.update({key: names for key, names in optional.items() if names})
        if self.process_state != DEFAULT_PROCESS_STATE:
            fields["process_state"] = self.process_state
        return fields


def parse_feature_flag_options(
    table: Mapping[str, object],  # sarj-noqa: SARJ528 -- TOML members stay unchecked until each key is validated.
) -> FeatureFlagOptions | None:
    if not table:
        return None
    unknown = sorted(set(table) - {*_IDENTIFIER_KEYS, *_DOTTED_KEYS})
    if unknown:
        message = f"{_LABEL} does not support: {', '.join(unknown)}"
        raise ValueError(message)
    names = {key: _names(table, key, _IDENTIFIER) for key in _IDENTIFIER_KEYS if key in table}
    names.update({key: _names(table, key, _DOTTED) for key in _DOTTED_KEYS if key in table})
    missing = [key for key in _REQUIRED if not names.get(key)]
    if missing:
        message = f"{_LABEL} requires nonempty: {', '.join(missing)}"
        raise ValueError(message)
    return FeatureFlagOptions(**names)


def _names(
    table: Mapping[str, object],  # sarj-noqa: SARJ528 -- the selected TOML member is validated as a name array below.
    key: str,
    pattern: re.Pattern[str],
) -> tuple[str, ...]:
    items = raw if _is_toml_array(raw := table[key]) else None
    names = tuple(item for item in items or () if isinstance(item, str) and pattern.fullmatch(item))
    if items is None or len(names) != len(items) or len(names) != len(set(names)):
        message = f"{_LABEL}.{key} must be an array of unique Python names"
        raise ValueError(message)
    return names


def _is_toml_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


@final
class FeatureFlagFacts:
    def __init__(self) -> None:
        self._directories: dict[Path, FeatureFlagOptions | None] = {}

    def options(self, path: Path) -> FeatureFlagOptions | None:
        try:
            directory = path.resolve().parent
        except OSError, RuntimeError:
            return None
        if directory not in self._directories:
            self._directories[directory] = _nearest_options(directory)
        return self._directories[directory]


def _nearest_options(directory: Path) -> FeatureFlagOptions | None:
    for ancestor in (directory, *directory.parents)[:_MAX_ANCESTORS]:
        manifest = ancestor / MANIFEST_NAME
        if manifest.is_file():
            return _manifest_options(manifest)
        if (ancestor / ".git").exists():
            return None
    return None


def _manifest_options(manifest: Path) -> FeatureFlagOptions | None:
    try:
        document: object = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except OSError, UnicodeError, tomllib.TOMLDecodeError:
        return None
    engine = document.get(ENGINE_TABLE) if _is_toml_table(document) else None
    rule = engine.get(RULE_TABLE) if _is_toml_table(engine) else None
    if rule is None:
        return None
    if not _is_toml_table(rule):
        message = f"{_LABEL} must be a table"
        raise ValueError(message)
    return parse_feature_flag_options({key: member for key, member in rule.items() if isinstance(key, str)})


def _is_toml_table(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)
